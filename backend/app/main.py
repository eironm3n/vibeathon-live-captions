"""Backend de la Vibeathon: transcripción + traducción simultánea a escala.

Endpoints:
  WS  /ws/ingest/{session_id}    -> un productor de audio (mic, archivo o
                                     stream) envía frames PCM16 16kHz mono.
  WS  /ws/captions/{session_id}  -> un visor recibe CaptionEvent en vivo
                                     para esa sesión (?lang=original|es).
  GET /api/sessions              -> sesiones activas (para el selector del
                                     frontend y para verificar N5).
  GET /api/sessions/{id}/export  -> transcripción completa en srt/vtt/txt
                                     (funciona con sesiones activas o ya
                                     terminadas).
  GET /health                    -> healthcheck.
  /                              -> vista de audiencia (frontend estático).
  /overlay.html                  -> vista minimal con fondo transparente,
                                     para usar como Browser Source en OBS.
"""
import logging

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import export as export_
from .config import FRONTEND_DIR
from .session_manager import SessionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Nerdearla Vibeathon - Subtítulos en vivo")
manager = SessionManager()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/sessions")
async def list_sessions():
    return {"sessions": manager.list_ids()}


_EXPORT_MEDIA_TYPES = {"srt": "text/plain", "vtt": "text/vtt", "txt": "text/plain"}


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: str, lang: str = "original", fmt: str = "srt"):
    if fmt not in _EXPORT_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="formato inválido: usar srt, vtt o txt")

    hub = manager.get_hub_for_export(session_id)
    if hub is None:
        raise HTTPException(status_code=404, detail="sesión no encontrada")

    events = hub.history(lang)
    if not events:
        raise HTTPException(
            status_code=404,
            detail=f"la sesión '{session_id}' no tiene subtítulos finales para el idioma '{lang}'",
        )

    builder = {"srt": export_.to_srt, "vtt": export_.to_vtt, "txt": export_.to_txt}[fmt]
    content = builder(events)
    filename = f"{session_id}-{lang}.{fmt}"
    return Response(
        content=content,
        media_type=_EXPORT_MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.websocket("/ws/ingest/{session_id}")
async def ws_ingest(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        session = await manager.get_or_create(session_id)
    except Exception:
        logger.exception(
            "No se pudo iniciar la sesión %s (¿GEMINI_API_KEY configurada?)", session_id
        )
        await websocket.close(code=1011, reason="No se pudo iniciar la sesión Gemini Live")
        return
    logger.info("Productor de audio conectado a la sesión %s", session_id)
    try:
        while True:
            chunk = await websocket.receive_bytes()
            await session.bridge.send_audio(chunk)
    except WebSocketDisconnect:
        pass
    finally:
        logger.info("Productor de audio desconectado de la sesión %s", session_id)
        await manager.remove(session_id)


@app.websocket("/ws/captions/{session_id}")
async def ws_captions(websocket: WebSocket, session_id: str):
    await websocket.accept()
    lang = websocket.query_params.get("lang", "original")

    session = manager.get(session_id)
    if session is None:
        await websocket.send_json({"error": "session_not_found"})
        await websocket.close()
        return

    queue = session.hub.subscribe()
    try:
        while True:
            event = await queue.get()
            if event.lang != lang:
                continue
            await websocket.send_json(event.model_dump())
    except WebSocketDisconnect:
        pass
    finally:
        session.hub.unsubscribe(queue)


# Vista de audiencia servida como archivos estáticos (index.html, app.js, style.css).
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
