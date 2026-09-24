"""Pub/sub en memoria: reparte los CaptionEvent de una sesión a sus visores conectados."""
import asyncio

from .schemas import CaptionEvent


class CaptionHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event: CaptionEvent) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                # Un visor lento no debe frenar a los demás: descartamos su
                # mensaje más viejo y seguimos.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await queue.put(event)
