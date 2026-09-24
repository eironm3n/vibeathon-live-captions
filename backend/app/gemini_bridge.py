"""Puente entre una sesión de audio y la Gemini Live API.

Diseño (validado contra la API real, ver notas abajo): el audio que llega
de a poco por `send_audio()` se junta en un buffer y, cada `SEGMENT_SECONDS`
segundos, se procesa como un turno independiente y corto contra la Live
API: se abre una conexión, se manda el segmento completo, se le indica que
terminó (`audio_stream_end`) y se leen dos salidas de esa misma conexión:
  - transcripción del segmento en el idioma original (N2), vía
    `input_audio_transcription`.
  - traducción del segmento al idioma destino (N3): el modelo, instruido
    por `system_instruction`, responde en `output_audio_transcription`
    (ver nota sobre por qué no se usa texto plano).
Los segmentos se procesan en orden, uno a la vez, para no mezclar el orden
de los subtítulos de una misma sesión.

Por qué segmentos y no una única conexión para toda la charla: se probó
mantener una sola conexión Live abierta durante toda la sesión, pero el
modelo (`gemini-3.1-flash-live-preview`, la única familia "Live" disponible
al momento de probar esto) solo responde a UN turno por conexión — ni la
detección automática de silencio (VAD) ni activity_start/activity_end
manual dispararon una segunda respuesta dentro de la misma conexión. Abrir
una conexión nueva por segmento sí funciona de forma confiable, a costa de
algo de latencia (los subtítulos de un segmento llegan agrupados, no
palabra por palabra).

Por qué se pide audio y no texto: estos modelos "audio nativo" no soportan
`response_modalities=["TEXT"]` (responden solo con audio hablado). Para
obtener la traducción como texto sin reproducir ese audio, se pide de
todos modos `response_modalities=["AUDIO"]` con `output_audio_transcription`
habilitado, y se descarta el audio en sí — solo se usa su transcripción.
Esto agrega latencia (el modelo tiene que generar el audio completo antes
de poder devolver su transcripción), es la principal oportunidad de
optimización a futuro (ver README).
"""
import asyncio
import logging
from typing import Awaitable, Callable

from google import genai
from google.genai import types

from .config import AUDIO_MIME_TYPE, GEMINI_API_KEY, GEMINI_MODEL, TARGET_LANGUAGE
from .schemas import CaptionEvent

logger = logging.getLogger(__name__)

OnCaption = Callable[[CaptionEvent], Awaitable[None]]

# Cuánto audio se junta antes de pedirle una transcripción/traducción a
# Gemini. Más chico = subtítulos más frecuentes pero con menos contexto por
# pedido (y más conexiones abiertas); más grande = al revés.
SEGMENT_SECONDS = 8

# Tamaño de cada frame que se manda dentro de un segmento (no afecta la
# latencia, solo evita mandar un único blob gigante de una).
SEND_CHUNK_BYTES = 3200

_LANGUAGE_NAMES = {
    "es": "español",
    "en": "inglés",
    "pt": "portugués",
}


def _translation_prompt(target_lang: str) -> str:
    target_name = _LANGUAGE_NAMES.get(target_lang, target_lang)
    return (
        "Sos un intérprete simultáneo para una conferencia técnica. "
        "Vas a recibir un fragmento de audio en vivo de una charla. "
        f"Traducí todo lo que se dice al {target_name}. "
        "Si el audio ya está en ese idioma, respondé con el mismo texto "
        "(no hace falta traducir). "
        "Devolvé ÚNICAMENTE la traducción como texto plano, sin agregar "
        "comentarios, aclaraciones ni marcas de idioma."
    )


class GeminiBridge:
    """Agrupa el audio de una sesión en segmentos y los traduce en orden."""

    def __init__(self, session_id: str, on_caption: OnCaption, target_lang: str | None = None):
        self.session_id = session_id
        self._on_caption = on_caption
        self._target_lang = target_lang or TARGET_LANGUAGE

        self._client = genai.Client(api_key=GEMINI_API_KEY)

        self._buffer = bytearray()
        self._buffer_lock = asyncio.Lock()
        self._segment_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        self._flush_task: asyncio.Task | None = None
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        if not GEMINI_API_KEY:
            logger.warning(
                "GEMINI_API_KEY no está configurada; la sesión %s no va a "
                "recibir transcripción/traducción real.",
                self.session_id,
            )
        self._flush_task = asyncio.create_task(self._flush_loop())
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Bridge de sesión %s iniciado (segmentos de %ss)", self.session_id, SEGMENT_SECONDS)

    async def send_audio(self, chunk: bytes) -> None:
        async with self._buffer_lock:
            self._buffer.extend(chunk)

    async def close(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
        # Procesamos lo que haya quedado en el buffer, aunque no haya
        # llegado a juntar SEGMENT_SECONDS de audio.
        await self._cut_segment()
        await self._segment_queue.put(None)  # señal de "no hay más segmentos"
        if self._worker_task:
            await self._worker_task
        logger.info("Bridge de sesión %s cerrado", self.session_id)

    async def _flush_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(SEGMENT_SECONDS)
                await self._cut_segment()
        except asyncio.CancelledError:
            pass

    async def _cut_segment(self) -> None:
        async with self._buffer_lock:
            if not self._buffer:
                return
            segment = bytes(self._buffer)
            self._buffer.clear()
        await self._segment_queue.put(segment)

    async def _worker_loop(self) -> None:
        while True:
            segment = await self._segment_queue.get()
            if segment is None:
                break
            await self._process_segment(segment)

    async def _process_segment(self, audio_bytes: bytes) -> None:
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=types.Content(
                parts=[types.Part(text=_translation_prompt(self._target_lang))]
            ),
        )
        try:
            async with self._client.aio.live.connect(model=GEMINI_MODEL, config=config) as session:
                for i in range(0, len(audio_bytes), SEND_CHUNK_BYTES):
                    await session.send_realtime_input(
                        audio=types.Blob(
                            data=audio_bytes[i : i + SEND_CHUNK_BYTES], mime_type=AUDIO_MIME_TYPE
                        )
                    )
                await session.send_realtime_input(audio_stream_end=True)

                orig_text = ""
                trans_text = ""
                async for response in session.receive():
                    server_content = getattr(response, "server_content", None)
                    if server_content is None:
                        continue
                    input_transcription = server_content.input_transcription
                    if input_transcription and input_transcription.text:
                        orig_text += input_transcription.text
                    output_transcription = server_content.output_transcription
                    if output_transcription and output_transcription.text:
                        trans_text += output_transcription.text
                    if server_content.turn_complete:
                        break

                if orig_text:
                    await self._emit("original", orig_text, is_final=True)
                if trans_text:
                    await self._emit(self._target_lang, trans_text, is_final=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Error procesando un segmento de audio de la sesión %s", self.session_id
            )

    async def _emit(self, lang: str, text: str, is_final: bool) -> None:
        await self._on_caption(
            CaptionEvent(session_id=self.session_id, lang=lang, text=text, is_final=is_final)
        )
