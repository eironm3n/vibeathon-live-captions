"""Genera la transcripción completa de una sesión en SRT, VTT o texto plano."""
from .schemas import CaptionEvent


def _format_srt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hh, millis = divmod(millis, 3_600_000)
    mm, millis = divmod(millis, 60_000)
    ss, millis = divmod(millis, 1_000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{millis:03d}"


def _format_vtt_time(seconds: float) -> str:
    return _format_srt_time(seconds).replace(",", ".")


def _timed(events: list[CaptionEvent]) -> list[tuple[float, float, str]]:
    """Completa start/end para eventos que no los tengan (fallback: 4s c/u)."""
    result = []
    cursor = 0.0
    for event in events:
        if event.start_s is not None and event.end_s is not None:
            start, end = event.start_s, event.end_s
        else:
            start, end = cursor, cursor + 4.0
        cursor = max(cursor, end)
        result.append((start, end, event.text))
    return result


def to_srt(events: list[CaptionEvent]) -> str:
    lines = []
    for i, (start, end, text) in enumerate(_timed(events), start=1):
        lines.append(str(i))
        lines.append(f"{_format_srt_time(start)} --> {_format_srt_time(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def to_vtt(events: list[CaptionEvent]) -> str:
    lines = ["WEBVTT", ""]
    for start, end, text in _timed(events):
        lines.append(f"{_format_vtt_time(start)} --> {_format_vtt_time(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def to_txt(events: list[CaptionEvent]) -> str:
    return "\n".join(event.text for event in events)
