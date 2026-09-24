"""Pub/sub en memoria: reparte los CaptionEvent de una sesión a sus visores conectados."""
import asyncio

from .schemas import CaptionEvent


class CaptionHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        # Historial de subtítulos finales por idioma, para poder exportar
        # la transcripción completa de una sesión (SRT/VTT/texto) incluso
        # después de que termine.
        self._history: dict[str, list[CaptionEvent]] = {}

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event: CaptionEvent) -> None:
        if event.is_final:
            self._history.setdefault(event.lang, []).append(event)
        for queue in list(self._subscribers):
            if queue.full():
                # Un visor lento no debe frenar a los demás: descartamos su
                # mensaje más viejo y seguimos.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await queue.put(event)

    def history(self, lang: str) -> list[CaptionEvent]:
        return list(self._history.get(lang, []))

    def available_langs(self) -> list[str]:
        return list(self._history.keys())
