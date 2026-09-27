"""Contrato común de los motores de transcripción/traducción."""
from dataclasses import dataclass
from typing import Protocol


class EngineError(RuntimeError):
    """El motor no pudo procesar un segmento (se registra y se sigue con el próximo)."""


@dataclass
class SegmentResult:
    original: str  # transcripción en el idioma hablado
    translated: str | None  # traducción; None si no hubo (falló o no aplica)


class Engine(Protocol):
    name: str
    # Segmentos de una misma sesión que pueden procesarse a la vez. Los
    # resultados siempre se publican en orden, sin importar cuál termine antes.
    max_parallel_segments: int

    async def start(self) -> None:
        """Prepara el motor (validar config, cargar modelos). Se llama una vez al arrancar."""

    async def process(self, pcm: bytes, source_lang: str, target_lang: str) -> SegmentResult:
        """Transcribe (y traduce) un segmento de audio PCM16 mono 16 kHz."""
        ...
