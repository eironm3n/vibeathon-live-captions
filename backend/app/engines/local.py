"""Motor local: Whisper (faster-whisper) para transcribir + un traductor offline.

No necesita key ni conexión (salvo para descargar los modelos la primera
vez) y el audio nunca sale de la máquina. El costo es CPU/GPU: como
referencia, `small` en int8 procesa 8 s de audio en ~3 s en un CPU de
escritorio de 12 hilos; con más sesiones simultáneas conviene `base` o GPU.
"""
import asyncio
import logging

from ..config import (
    ARGOS_AUTO_DOWNLOAD,
    ARGOS_INDEX_URL,
    LOCAL_MAX_PARALLEL,
    MODELS_DIR,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
    TRANSLATOR,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_MODEL,
)
from ..glossary import GLOSSARY
from .base import EngineError, SegmentResult
from .translators import ArgosTranslator, NoTranslator, OllamaTranslator, Translator

logger = logging.getLogger(__name__)


def create_translator(name: str = TRANSLATOR) -> Translator:
    if name == "argos":
        return ArgosTranslator(MODELS_DIR, ARGOS_INDEX_URL, ARGOS_AUTO_DOWNLOAD)
    if name == "ollama":
        return OllamaTranslator(OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT_SECONDS)
    if name == "none":
        return NoTranslator()
    raise EngineError(f"TRANSLATOR desconocido: {name!r} (usar argos, ollama o none)")


class LocalEngine:
    name = "local"
    max_parallel_segments = max(1, LOCAL_MAX_PARALLEL)

    def __init__(self) -> None:
        self._translator = create_translator()
        self._model = None
        self._model_ready: asyncio.Task | None = None
        # Tope global (todas las sesiones comparten el mismo modelo): evita
        # saturar el CPU corriendo varias inferencias a la vez.
        self._inference_slots = asyncio.Semaphore(max(1, LOCAL_MAX_PARALLEL))

    async def start(self) -> None:
        try:
            import faster_whisper  # noqa: F401
        except ImportError as exc:
            raise EngineError(
                "CAPTION_ENGINE=local requiere las dependencias de backend/requirements-local.txt "
                "(pip install -r backend/requirements-local.txt)."
            ) from exc
        # El modelo se carga en segundo plano (la primera vez además se
        # descarga) para que el servidor arranque enseguida.
        self._model_ready = asyncio.create_task(asyncio.to_thread(self._load_model))
        self._model_ready.add_done_callback(_log_load_result)

    def _load_model(self) -> None:
        from faster_whisper import WhisperModel

        logger.info("Cargando Whisper '%s' (%s/%s)...", WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE)
        self._model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
            download_root=str(MODELS_DIR / "whisper"),
        )

    async def process(self, pcm: bytes, source_lang: str, target_lang: str) -> SegmentResult:
        await self._model_ready
        async with self._inference_slots:
            pieces, detected = await asyncio.to_thread(self._transcribe, pcm, source_lang)

        pieces = [GLOSSARY.apply_corrections(piece) for piece in pieces if piece]
        original = " ".join(pieces)
        if not original:
            return SegmentResult(original="", translated=None)

        spoken = detected if source_lang == "auto" else source_lang.split("-")[0]
        try:
            translated = await self._translator.translate(pieces, spoken, target_lang.split("-")[0])
        except Exception:
            # Sin traducción igual se publica la transcripción original.
            logger.warning("Falló la traducción (%s); se publica solo el original", self._translator.name, exc_info=True)
            translated = None
        return SegmentResult(original=original, translated=translated)

    def _transcribe(self, pcm: bytes, source_lang: str) -> tuple[list[str], str]:
        import numpy as np

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, info = self._model.transcribe(
            samples,
            language=None if source_lang == "auto" else source_lang.split("-")[0],
            beam_size=1,  # prioriza latencia; con GPU se puede subir
            vad_filter=True,  # evita "alucinaciones" de Whisper sobre silencio
            condition_on_previous_text=False,
            hotwords=GLOSSARY.hotwords(),
        )
        return [segment.text.strip() for segment in segments], info.language


def _log_load_result(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    if task.exception():
        logger.error("No se pudo cargar Whisper: %s", task.exception())
    else:
        logger.info("Whisper listo")

