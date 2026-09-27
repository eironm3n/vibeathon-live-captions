"""Motor simulado: devuelve frases fijas sin mirar el audio.

Sirve para probar la vista de audiencia, el overlay de OBS, la exportación
o los tests sin key, sin GPU y sin descargar modelos.
"""
import asyncio
import itertools

from .base import SegmentResult

_PHRASES = [
    ("Welcome everyone, thanks for joining this session.", "Bienvenidos a todos, gracias por sumarse a esta sesión."),
    ("Today we will talk about open source and accessibility.", "Hoy vamos a hablar de open source y accesibilidad."),
    ("These captions are simulated: no audio is being analyzed.", "Estos subtítulos son simulados: no se está analizando audio."),
    ("Switch CAPTION_ENGINE to local or gemini for real captions.", "Cambiá CAPTION_ENGINE a local o gemini para subtítulos reales."),
]


class MockEngine:
    name = "mock"
    max_parallel_segments = 1

    def __init__(self, delay_seconds: float = 0.2):
        self._delay = delay_seconds
        self._phrases = itertools.cycle(_PHRASES)

    async def start(self) -> None:
        pass

    async def process(self, pcm: bytes, source_lang: str, target_lang: str) -> SegmentResult:
        await asyncio.sleep(self._delay)
        original, spanish = next(self._phrases)
        translated = spanish if target_lang == "es" else f"[{target_lang}] {original}"
        return SegmentResult(original=original, translated=translated)
