"""Motor Gemini Live API (opcional, requiere GEMINI_API_KEY).

Cada segmento es un turno independiente y corto contra la Live API: se abre
una conexión, se manda el segmento completo, se le indica que terminó
(`audio_stream_end`) y se leen dos salidas de esa misma conexión:
  - transcripción en el idioma original, vía `input_audio_transcription`.
  - traducción al idioma destino: el modelo, instruido por
    `system_instruction`, responde en `output_audio_transcription`.

Por qué una conexión por segmento: con `gemini-3.1-flash-live-preview` se
probó mantener una sola conexión abierta durante toda la charla, pero el
modelo solo respondía a UN turno por conexión — ni la detección automática
de silencio ni activity_start/activity_end dispararon una segunda respuesta.

Por qué se pide audio y no texto: estos modelos "audio nativo" no soportan
`response_modalities=["TEXT"]`. Se pide `["AUDIO"]` con
`output_audio_transcription` y se descarta el audio en sí. Esto agrega
latencia (el modelo genera el audio completo antes de devolver su
transcripción); por eso se procesan varios segmentos en paralelo.

Tener en cuenta: los modelos "preview" pueden cambiar o desaparecer, el
plan gratuito tiene límites estrictos, y según los términos de Google los
datos enviados con el plan gratuito pueden usarse para mejorar sus productos.
"""
import logging

from ..config import AUDIO_MIME_TYPE, GEMINI_API_KEY, GEMINI_MAX_PARALLEL, GEMINI_MODEL
from ..glossary import GLOSSARY
from ..languages import language_name
from .base import EngineError, SegmentResult

logger = logging.getLogger(__name__)

# Tamaño de cada frame que se manda dentro de un segmento (solo evita
# mandar un único blob gigante de una).
SEND_CHUNK_BYTES = 3200


def _translation_prompt(source_lang: str, target_lang: str) -> str:
    source_hint = (
        f"El audio está en {language_name(source_lang)}. " if source_lang != "auto" else ""
    )
    base = (
        "Sos un intérprete simultáneo para una conferencia técnica. "
        "Vas a recibir un fragmento de audio en vivo de una charla. "
        f"{source_hint}"
        f"Traducí todo lo que se dice al {language_name(target_lang)}. "
        "Si el audio ya está en ese idioma, respondé con el mismo texto "
        "(no hace falta traducir). "
        "Devolvé ÚNICAMENTE la traducción como texto plano, sin agregar "
        "comentarios, aclaraciones ni marcas de idioma."
    )
    return base + GLOSSARY.prompt_instructions()


class GeminiEngine:
    name = "gemini"
    max_parallel_segments = max(1, GEMINI_MAX_PARALLEL)

    def __init__(self) -> None:
        self._client = None

    async def start(self) -> None:
        if not GEMINI_API_KEY:
            raise EngineError(
                "CAPTION_ENGINE=gemini requiere GEMINI_API_KEY en .env "
                "(o usá CAPTION_ENGINE=local, que no necesita key)."
            )
        # Import diferido: google-genai solo hace falta con este motor.
        from google import genai

        self._client = genai.Client(api_key=GEMINI_API_KEY)

    async def process(self, pcm: bytes, source_lang: str, target_lang: str) -> SegmentResult:
        from google.genai import types

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=types.Content(
                parts=[types.Part(text=_translation_prompt(source_lang, target_lang))]
            ),
        )
        async with self._client.aio.live.connect(model=GEMINI_MODEL, config=config) as session:
            for i in range(0, len(pcm), SEND_CHUNK_BYTES):
                await session.send_realtime_input(
                    audio=types.Blob(data=pcm[i : i + SEND_CHUNK_BYTES], mime_type=AUDIO_MIME_TYPE)
                )
            await session.send_realtime_input(audio_stream_end=True)

            orig_text = ""
            trans_text = ""
            async for response in session.receive():
                server_content = getattr(response, "server_content", None)
                if server_content is None:
                    continue
                if server_content.input_transcription and server_content.input_transcription.text:
                    orig_text += server_content.input_transcription.text
                if server_content.output_transcription and server_content.output_transcription.text:
                    trans_text += server_content.output_transcription.text
                if server_content.turn_complete:
                    break

        original = GLOSSARY.apply_corrections(orig_text.strip())
        return SegmentResult(original=original, translated=trans_text.strip() or None)
