"""Pipeline de una sesión: junta el audio en segmentos y los pasa por el motor.

El audio llega de a poco por `send_audio()`. Se corta un segmento en la
primera pausa (silencio) después de `SEGMENT_MIN_SECONDS`, o sí o sí al
llegar a `SEGMENT_MAX_SECONDS`: así los cortes caen entre frases y no en la
mitad de una palabra.

Los segmentos se procesan en paralelo hasta `engine.max_parallel_segments`,
pero los subtítulos se publican siempre en el orden del audio. Si el motor
es más lento que el audio y se acumulan más de `MAX_PENDING_SEGMENTS`
segmentos esperando, los nuevos se descartan: preferimos perder un segmento
a que los subtítulos se atrasen cada vez más durante una charla larga.
"""
import asyncio
import logging
import math
from array import array
from dataclasses import dataclass
from typing import Awaitable, Callable

from .config import AUDIO_SAMPLE_RATE, MAX_PENDING_SEGMENTS, SEGMENT_MAX_SECONDS, SEGMENT_MIN_SECONDS
from .engines import Engine, SegmentResult
from .schemas import CaptionEvent

logger = logging.getLogger(__name__)

OnCaption = Callable[[CaptionEvent], Awaitable[None]]

CHECK_INTERVAL_SECONDS = 0.25
# Una pausa es cuando los últimos SILENCE_TAIL_SECONDS tienen menos energía
# que SILENCE_RATIO veces la del segmento (relativo, para no depender del
# volumen de la fuente).
SILENCE_TAIL_SECONDS = 0.4
SILENCE_RATIO = 0.35
# Segmentos por debajo de este nivel (RMS, escala PCM16) se consideran
# silencio y ni se mandan al motor.
QUIET_SEGMENT_RMS = 80.0


@dataclass
class _Segment:
    pcm: bytes
    start_s: float
    end_s: float


class SegmentPipeline:
    def __init__(
        self,
        session_id: str,
        engine: Engine,
        source_lang: str,
        target_lang: str,
        on_caption: OnCaption,
        *,
        min_seconds: float = SEGMENT_MIN_SECONDS,
        max_seconds: float = SEGMENT_MAX_SECONDS,
        max_pending: int = MAX_PENDING_SEGMENTS,
    ):
        self.session_id = session_id
        self.source_lang = source_lang
        self.target_lang = target_lang
        self._engine = engine
        self._on_caption = on_caption
        self._min_samples = int(min_seconds * AUDIO_SAMPLE_RATE)
        self._max_samples = int(max(max_seconds, min_seconds) * AUDIO_SAMPLE_RATE)
        self._max_pending = max(1, max_pending)

        self._chunks: list[bytes] = []
        self._chunk_energy: list[tuple[int, float]] = []  # (muestras, suma de cuadrados)
        self._buffered_samples = 0
        # Segundos de audio ya cortados: dan a cada subtítulo un timestamp
        # relativo al audio (no a cuándo respondió el motor) para exportar SRT/VTT.
        self._elapsed_seconds = 0.0

        self._pending: asyncio.Queue[tuple[_Segment, asyncio.Task] | None] = asyncio.Queue()
        self._engine_slots = asyncio.Semaphore(max(1, engine.max_parallel_segments))
        self._cut_task: asyncio.Task | None = None
        self._emit_task: asyncio.Task | None = None
        self.dropped_segments = 0

    async def start(self) -> None:
        self._cut_task = asyncio.create_task(self._cut_loop())
        self._emit_task = asyncio.create_task(self._emit_loop())
        logger.info(
            "Sesión %s: pipeline iniciado (motor %s, %s -> %s)",
            self.session_id, self._engine.name, self.source_lang, self.target_lang,
        )

    def send_audio(self, chunk: bytes) -> None:
        """Agrega audio PCM16 (largo par, validado por quien llama)."""
        samples = array("h", chunk)
        self._chunks.append(chunk)
        self._chunk_energy.append((len(samples), float(sum(s * s for s in samples))))
        self._buffered_samples += len(samples)

    async def close(self) -> None:
        """Procesa lo que quedó en el buffer y espera a publicar todo lo pendiente."""
        if self._cut_task:
            self._cut_task.cancel()
            await asyncio.gather(self._cut_task, return_exceptions=True)
        self._cut()
        self._pending.put_nowait(None)
        if self._emit_task:
            await self._emit_task
        if self.dropped_segments:
            logger.warning(
                "Sesión %s: se descartaron %d segmentos porque el motor no daba abasto",
                self.session_id, self.dropped_segments,
            )
        logger.info("Sesión %s: pipeline cerrado", self.session_id)

    async def _cut_loop(self) -> None:
        while True:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            if self._should_cut():
                self._cut()

    def _should_cut(self) -> bool:
        if self._buffered_samples >= self._max_samples:
            return True
        if self._buffered_samples < self._min_samples:
            return False
        return self._tail_is_silent()

    def _tail_is_silent(self) -> bool:
        total_n = sum(n for n, _ in self._chunk_energy)
        total_sq = sum(sq for _, sq in self._chunk_energy)
        tail_n, tail_sq = 0, 0.0
        for n, sq in reversed(self._chunk_energy):
            tail_n += n
            tail_sq += sq
            if tail_n >= SILENCE_TAIL_SECONDS * AUDIO_SAMPLE_RATE:
                break
        segment_rms = math.sqrt(total_sq / total_n)
        tail_rms = math.sqrt(tail_sq / tail_n)
        return tail_rms <= segment_rms * SILENCE_RATIO

    def _cut(self) -> None:
        if not self._buffered_samples:
            return
        pcm = b"".join(self._chunks)
        samples = self._buffered_samples
        rms = math.sqrt(sum(sq for _, sq in self._chunk_energy) / samples)
        self._chunks.clear()
        self._chunk_energy.clear()
        self._buffered_samples = 0

        segment = _Segment(pcm, self._elapsed_seconds, self._elapsed_seconds + samples / AUDIO_SAMPLE_RATE)
        self._elapsed_seconds = segment.end_s

        if rms < QUIET_SEGMENT_RMS:
            return
        if self._pending.qsize() >= self._max_pending:
            self.dropped_segments += 1
            logger.warning(
                "Sesión %s: motor saturado, se descarta el segmento %.1fs-%.1fs",
                self.session_id, segment.start_s, segment.end_s,
            )
            return
        self._pending.put_nowait((segment, asyncio.create_task(self._process(segment))))

    async def _process(self, segment: _Segment) -> SegmentResult | None:
        async with self._engine_slots:
            try:
                return await self._engine.process(segment.pcm, self.source_lang, self.target_lang)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Sesión %s: error procesando el segmento %.1fs-%.1fs",
                    self.session_id, segment.start_s, segment.end_s,
                )
                return None

    async def _emit_loop(self) -> None:
        while True:
            item = await self._pending.get()
            if item is None:
                return
            segment, task = item
            result = await task
            if result is None:
                continue
            for lang, text in (("original", result.original), (self.target_lang, result.translated)):
                if text:
                    await self._on_caption(
                        CaptionEvent(
                            session_id=self.session_id,
                            lang=lang,
                            text=text,
                            is_final=True,
                            start_s=segment.start_s,
                            end_s=segment.end_s,
                        )
                    )
