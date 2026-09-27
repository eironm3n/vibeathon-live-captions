"""Pub/sub en memoria: reparte los CaptionEvent de una sesión a sus visores conectados."""
import asyncio

from .config import MAX_HISTORY_EVENTS
from .schemas import CaptionEvent

# Lo que reciben los visores: un subtítulo, o None cuando la sesión terminó.
HubMessage = CaptionEvent | None


class CaptionHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[HubMessage]] = set()
        # Historial de subtítulos finales por idioma, para poder exportar
        # la transcripción completa de una sesión (SRT/VTT/texto) incluso
        # después de que termine.
        self._history: dict[str, list[CaptionEvent]] = {}
        self.closed = False

    def subscribe(self) -> asyncio.Queue[HubMessage]:
        queue: asyncio.Queue[HubMessage] = asyncio.Queue(maxsize=100)
        if self.closed:
            queue.put_nowait(None)
        else:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[HubMessage]) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event: CaptionEvent) -> None:
        if event.is_final:
            history = self._history.setdefault(event.lang, [])
            if len(history) < MAX_HISTORY_EVENTS:
                history.append(event)
        self._broadcast(event)

    def close(self) -> None:
        """Avisa a los visores que la sesión terminó (para que se reconecten o muestren el fin)."""
        self.closed = True
        self._broadcast(None)
        self._subscribers.clear()

    def _broadcast(self, message: HubMessage) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                # Un visor lento no debe frenar a los demás: descartamos su
                # mensaje más viejo y seguimos.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(message)

    def history(self, lang: str) -> list[CaptionEvent]:
        return list(self._history.get(lang, []))
