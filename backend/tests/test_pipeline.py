import asyncio

from app.engines import SegmentResult
from app.pipeline import SegmentPipeline

from conftest import silence, tone


class FakeEngine:
    """Motor de prueba: cada segmento tarda lo que indica `delays` (en orden)."""

    name = "fake"

    def __init__(self, delays, max_parallel=3):
        self.max_parallel_segments = max_parallel
        self._delays = list(delays)
        self.calls = 0

    async def start(self):
        pass

    async def process(self, pcm, source_lang, target_lang):
        index = self.calls
        self.calls += 1
        await asyncio.sleep(self._delays[index])
        return SegmentResult(original=f"seg{index}", translated=f"es{index}")


def _run(coro):
    return asyncio.run(coro)


async def _feed(engine, segments, **kwargs):
    events = []

    async def collect(event):
        events.append(event)

    pipeline = SegmentPipeline("s", engine, "en", "es", collect, min_seconds=60, max_seconds=60, **kwargs)
    await pipeline.start()
    for pcm in segments:
        pipeline.send_audio(pcm)
        pipeline._cut()  # corte manual: el test no depende de tiempos reales
    await pipeline.close()
    return pipeline, events


def test_results_are_published_in_audio_order_even_if_engine_finishes_out_of_order():
    engine = FakeEngine(delays=[0.3, 0.1, 0.0])
    _, events = _run(_feed(engine, [tone(1), tone(1), tone(1)]))
    assert [e.text for e in events if e.lang == "original"] == ["seg0", "seg1", "seg2"]
    assert [e.text for e in events if e.lang == "es"] == ["es0", "es1", "es2"]
    assert [(e.start_s, e.end_s) for e in events if e.lang == "es"] == [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]


def test_silent_segments_are_not_sent_to_the_engine_but_advance_time():
    engine = FakeEngine(delays=[0.0])
    _, events = _run(_feed(engine, [silence(2), tone(1)]))
    assert engine.calls == 1
    assert events[0].start_s == 2.0


def test_segments_are_dropped_when_engine_cannot_keep_up():
    engine = FakeEngine(delays=[0.2] * 5, max_parallel=1)
    pipeline, events = _run(_feed(engine, [tone(1)] * 5, max_pending=2))
    assert pipeline.dropped_segments == 3
    assert len([e for e in events if e.lang == "original"]) == 2


def test_engine_errors_skip_the_segment_and_continue():
    class FlakyEngine(FakeEngine):
        async def process(self, pcm, source_lang, target_lang):
            if self.calls == 0:
                self.calls += 1
                raise RuntimeError("falla simulada")
            return await super().process(pcm, source_lang, target_lang)

    engine = FlakyEngine(delays=[0.0, 0.0])
    _, events = _run(_feed(engine, [tone(1), tone(1)]))
    assert [e.text for e in events if e.lang == "original"] == ["seg1"]


def test_cut_on_pause_after_min_seconds():
    async def scenario():
        pipeline = SegmentPipeline(
            "s", FakeEngine([0.0]), "en", "es", lambda e: None, min_seconds=1, max_seconds=10
        )
        pipeline.send_audio(tone(0.8))
        assert not pipeline._should_cut()  # todavía no llegó al mínimo
        pipeline.send_audio(tone(0.5))
        assert not pipeline._should_cut()  # pasó el mínimo, pero sigue hablando
        pipeline.send_audio(silence(0.5))
        assert pipeline._should_cut()  # pausa: se corta acá

    _run(scenario())
