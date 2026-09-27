"""Registro de sesiones activas (una por escenario/audio en vivo).

Cada sesión corre de forma independiente (su propio pipeline + su propio
CaptionHub), así que soportar varias sesiones en paralelo es simplemente
tener varias entradas en este dict, hasta MAX_SESSIONS. El motor sí es
compartido: los modelos locales se cargan una sola vez.

Cada sesión admite un único productor de audio: un segundo productor con el
mismo id se rechaza (evita que alguien inyecte audio en una sesión ajena, y
que al desconectarse uno se corte la sesión del otro).

Cómo escalar más allá de un solo proceso: varias réplicas detrás de un
balanceador con "sticky routing" por session_id, o mover este registro a
un almacén compartido (Redis) si hay que descubrir sesiones entre réplicas.
"""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass

from .caption_hub import CaptionHub
from .config import ARCHIVE_MAX_SESSIONS, MAX_SESSIONS
from .engines import Engine
from .pipeline import SegmentPipeline


class SessionBusyError(Exception):
    """Ya hay un productor de audio conectado a esa sesión."""


class TooManySessionsError(Exception):
    """Se alcanzó MAX_SESSIONS."""


@dataclass
class Session:
    session_id: str
    hub: CaptionHub
    pipeline: SegmentPipeline

    def describe(self) -> dict:
        return {
            "id": self.session_id,
            "source_lang": self.pipeline.source_lang,
            "target_lang": self.pipeline.target_lang,
        }


class SessionManager:
    def __init__(
        self,
        engine: Engine,
        *,
        max_sessions: int = MAX_SESSIONS,
        archive_max: int = ARCHIVE_MAX_SESSIONS,
    ) -> None:
        self._engine = engine
        self._max_sessions = max_sessions
        self._archive_max = archive_max
        self._sessions: dict[str, Session] = {}
        # CaptionHub de sesiones ya terminadas, para exportar su transcripción
        # después. Se conservan las últimas `archive_max`; para guardar más
        # tiempo, exportá los archivos al terminar cada charla.
        self._archive: OrderedDict[str, CaptionHub] = OrderedDict()
        self._lock = asyncio.Lock()

    async def open(self, session_id: str, source_lang: str, target_lang: str) -> Session:
        async with self._lock:
            if session_id in self._sessions:
                raise SessionBusyError(session_id)
            if len(self._sessions) >= self._max_sessions:
                raise TooManySessionsError(session_id)

            hub = CaptionHub()
            pipeline = SegmentPipeline(session_id, self._engine, source_lang, target_lang, hub.publish)
            await pipeline.start()
            session = Session(session_id=session_id, hub=hub, pipeline=pipeline)
            self._sessions[session_id] = session
            return session

    async def close(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            return
        # Primero se termina de procesar lo que quedó en el buffer y recién
        # después se saca la sesión de las activas: así, quien exporte apenas
        # la sesión desaparece de /api/sessions ya obtiene el último segmento.
        await session.pipeline.close()
        async with self._lock:
            self._sessions.pop(session_id, None)
            self._archive.pop(session_id, None)
            self._archive[session_id] = session.hub
            while len(self._archive) > self._archive_max:
                self._archive.popitem(last=False)
        session.hub.close()

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list(self) -> list[dict]:
        return [session.describe() for session in self._sessions.values()]

    def get_hub_for_export(self, session_id: str) -> CaptionHub | None:
        """Devuelve el CaptionHub de una sesión activa o ya terminada."""
        session = self._sessions.get(session_id)
        if session:
            return session.hub
        return self._archive.get(session_id)
