"""Registro de sesiones activas (una por escenario/audio en vivo).

Cada sesión corre de forma independiente (su propia conexión Gemini Live +
su propio CaptionHub), por lo que soportar múltiples sesiones en paralelo
(requisito N5) es simplemente tener múltiples entradas en este dict: no hay
límite artificial más allá de los recursos del proceso.

Cómo escalar más allá de un solo proceso: correr varias réplicas de este
mismo contenedor detrás de un balanceador con "sticky routing" por
session_id (para que el productor y los visores de una sesión siempre
lleguen a la misma réplica), o mover este registro a un backend compartido
(Redis) si se necesita descubrir sesiones entre réplicas.
"""
import asyncio
from dataclasses import dataclass

from .caption_hub import CaptionHub
from .gemini_bridge import GeminiBridge


@dataclass
class Session:
    session_id: str
    hub: CaptionHub
    bridge: GeminiBridge


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, session_id: str) -> Session:
        async with self._lock:
            existing = self._sessions.get(session_id)
            if existing:
                return existing

            hub = CaptionHub()
            bridge = GeminiBridge(session_id=session_id, on_caption=hub.publish)
            await bridge.start()
            session = Session(session_id=session_id, hub=hub, bridge=bridge)
            self._sessions[session_id] = session
            return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list_ids(self) -> list[str]:
        return list(self._sessions.keys())

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            await session.bridge.close()
