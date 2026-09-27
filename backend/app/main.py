"""OpenCaption Live: subtítulos y traducción en vivo para conferencias.

Endpoints:
  WS  /ws/ingest/{session_id}    -> un productor de audio (mic, archivo o
                                     stream). Primer mensaje: JSON con el
                                     token; después, frames PCM16 16kHz mono.
  WS  /ws/captions/{session_id}  -> un visor recibe los subtítulos en vivo
                                     de esa sesión (?lang=original|<destino>).
  GET /api/sessions              -> sesiones activas y sus idiomas.
  GET /api/sessions/{id}/export  -> transcripción completa en srt/vtt/txt
                                     (sesiones activas o ya terminadas).
  GET /api/config                -> motor e idiomas por defecto.
  GET /health                    -> healthcheck.
  /                              -> vista de audiencia (frontend estático).
  /overlay.html                  -> vista para usar como Browser Source en OBS.
  /admin.html                    -> panel para emitir audio (requiere token).

Protocolo de ingesta (el token nunca viaja en la URL, así no queda en logs):
  cliente -> {"token": "...", "source_lang": "en", "target_lang": "es"}
  servidor -> {"type": "ready", ...}   (o cierra con un código 44xx)
  cliente -> frames binarios de audio
"""
import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import export as export_
from .config import (
    CAPTION_ENGINE,
    FRONTEND_DIR,
    INGEST_TOKEN,
    INGEST_TOKEN_GENERATED,
    MAX_AUDIO_FRAME_BYTES,
    SOURCE_LANGUAGE,
    TARGET_LANGUAGE,
)
from .engines import EngineError, create_engine
from .session_manager import SessionBusyError, SessionManager, TooManySessionsError
from .validation import is_valid_lang, is_valid_session_id, is_valid_source_lang

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx registra cada URL completa en INFO: ruido, y un riesgo si alguna
# URL llegara a llevar credenciales.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

HANDSHAKE_TIMEOUT_SECONDS = 10

# Códigos de cierre de WebSocket (rango 4000-4999, de uso libre por la app).
CLOSE_BAD_REQUEST = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_NOT_FOUND = 4404
CLOSE_BUSY = 4409
CLOSE_TOO_MANY = 4429


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_engine(CAPTION_ENGINE)
    try:
        await engine.start()
    except EngineError as exc:
        logger.error("%s", exc)
        raise
    app.state.manager = SessionManager(engine)
    logger.info("Motor de subtítulos: %s (%s -> %s por defecto)", engine.name, SOURCE_LANGUAGE, TARGET_LANGUAGE)
    if INGEST_TOKEN_GENERATED:
        logger.warning(
            "INGEST_TOKEN no está definido: se generó uno para esta ejecución.\n\n"
            "    Token para emitir audio: %s\n\n"
            "Para que sea fijo, definilo en .env (INGEST_TOKEN=...).",
            INGEST_TOKEN,
        )
    yield


app = FastAPI(title="OpenCaption Live", lifespan=lifespan)

_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self' ws: wss:; object-src 'none'; base-uri 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    csp = _CSP
    if request.url.path.endswith("admin.html"):
        # El panel de emisión no debe poder embeberse en otro sitio (clickjacking).
        csp += "; frame-ancestors 'none'"
    response.headers.setdefault("Content-Security-Policy", csp)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
    return response


def _manager(conn: Request | WebSocket) -> SessionManager:
    return conn.app.state.manager


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config")
async def get_config():
    return {"engine": CAPTION_ENGINE, "source_lang": SOURCE_LANGUAGE, "target_lang": TARGET_LANGUAGE}


@app.get("/api/sessions")
async def list_sessions(request: Request):
    return {"sessions": _manager(request).list()}


_EXPORT_MEDIA_TYPES = {"srt": "application/x-subrip", "vtt": "text/vtt", "txt": "text/plain"}


@app.get("/api/sessions/{session_id}/export")
async def export_session(request: Request, session_id: str, lang: str = "original", fmt: str = "srt"):
    if not is_valid_session_id(session_id):
        raise HTTPException(status_code=400, detail="id de sesión inválido")
    if lang != "original" and not is_valid_lang(lang):
        raise HTTPException(status_code=400, detail="idioma inválido")
    if fmt not in _EXPORT_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="formato inválido: usar srt, vtt o txt")

    hub = _manager(request).get_hub_for_export(session_id)
    if hub is None:
        raise HTTPException(status_code=404, detail="sesión no encontrada")

    events = hub.history(lang)
    if not events:
        raise HTTPException(status_code=404, detail="la sesión no tiene subtítulos para ese idioma")

    builder = {"srt": export_.to_srt, "vtt": export_.to_vtt, "txt": export_.to_txt}[fmt]
    return Response(
        content=builder(events),
        media_type=f"{_EXPORT_MEDIA_TYPES[fmt]}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{session_id}-{lang}.{fmt}"'},
    )


async def _close(websocket: WebSocket, code: int, reason: str = "") -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except RuntimeError:
        pass  # ya estaba cerrado


def _parse_handshake(message: dict) -> dict | None:
    text = message.get("text")
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _token_ok(candidate: object) -> bool:
    return isinstance(candidate, str) and hmac.compare_digest(
        candidate.encode("utf-8"), INGEST_TOKEN.encode("utf-8")
    )


@app.websocket("/ws/ingest/{session_id}")
async def ws_ingest(websocket: WebSocket, session_id: str):
    await websocket.accept()
    if not is_valid_session_id(session_id):
        await _close(websocket, CLOSE_BAD_REQUEST, "id de sesión inválido (a-z, 0-9, - y _; hasta 64)")
        return

    try:
        first = await asyncio.wait_for(websocket.receive(), timeout=HANDSHAKE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        await _close(websocket, CLOSE_BAD_REQUEST, "falta el mensaje de autenticación")
        return
    if first["type"] == "websocket.disconnect":
        return
    handshake = _parse_handshake(first)
    if handshake is None:
        await _close(websocket, CLOSE_BAD_REQUEST, "el primer mensaje debe ser JSON con el token")
        return
    if not _token_ok(handshake.get("token")):
        logger.warning("Ingesta rechazada para la sesión %s: token inválido", session_id)
        await _close(websocket, CLOSE_UNAUTHORIZED, "token inválido")
        return

    source_lang = str(handshake.get("source_lang") or SOURCE_LANGUAGE).lower()
    target_lang = str(handshake.get("target_lang") or TARGET_LANGUAGE).lower()
    if not is_valid_source_lang(source_lang) or not is_valid_lang(target_lang):
        await _close(websocket, CLOSE_BAD_REQUEST, "idioma inválido")
        return

    manager = _manager(websocket)
    try:
        session = await manager.open(session_id, source_lang, target_lang)
    except SessionBusyError:
        await _close(websocket, CLOSE_BUSY, "ya hay un emisor conectado a esa sesión")
        return
    except TooManySessionsError:
        await _close(websocket, CLOSE_TOO_MANY, "se alcanzó el máximo de sesiones simultáneas")
        return

    logger.info("Productor de audio conectado a la sesión %s", session_id)
    try:
        await websocket.send_json({"type": "ready", **session.describe(), "engine": CAPTION_ENGINE})
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            chunk = message.get("bytes")
            if chunk is None:
                continue  # mensajes de texto posteriores se ignoran
            if len(chunk) > MAX_AUDIO_FRAME_BYTES or len(chunk) % 2:
                await _close(websocket, CLOSE_BAD_REQUEST, "frame de audio inválido (PCM16, hasta 64 KB)")
                break
            session.pipeline.send_audio(chunk)
    except WebSocketDisconnect:
        pass
    finally:
        logger.info("Productor de audio desconectado de la sesión %s", session_id)
        await manager.close(session_id)


@app.websocket("/ws/captions/{session_id}")
async def ws_captions(websocket: WebSocket, session_id: str):
    await websocket.accept()
    lang = websocket.query_params.get("lang", "original")
    if not is_valid_session_id(session_id) or (lang != "original" and not is_valid_lang(lang)):
        await _close(websocket, CLOSE_BAD_REQUEST, "sesión o idioma inválido")
        return

    session = _manager(websocket).get(session_id)
    if session is None:
        await websocket.send_json({"type": "error", "error": "session_not_found"})
        await _close(websocket, CLOSE_NOT_FOUND, "sesión no encontrada")
        return

    queue = session.hub.subscribe()
    try:
        while True:
            event = await queue.get()
            if event is None:
                await websocket.send_json({"type": "ended"})
                await _close(websocket, 1000, "la sesión terminó")
                return
            if event.lang == lang:
                await websocket.send_json({"type": "caption", **event.model_dump()})
    except WebSocketDisconnect:
        pass
    finally:
        session.hub.unsubscribe(queue)


# Vista de audiencia servida como archivos estáticos.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
