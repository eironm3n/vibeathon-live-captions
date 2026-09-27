import json
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from conftest import TOKEN, tone


def _handshake(ws, token=TOKEN, **extra):
    ws.send_text(json.dumps({"token": token, **extra}))


def _close_code(ws) -> int:
    with pytest.raises(WebSocketDisconnect) as exc:
        while True:
            ws.receive_text()
    return exc.value.code


def _wait_until_no_sessions(client, timeout=5.0):
    deadline = time.monotonic() + timeout
    while client.get("/api/sessions").json()["sessions"]:
        assert time.monotonic() < deadline, "la sesión no se cerró a tiempo"
        time.sleep(0.05)


def test_health_and_security_headers(client):
    response = client.get("/health")
    assert response.json() == {"status": "ok"}
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    admin = client.get("/admin.html")
    assert "frame-ancestors 'none'" in admin.headers["content-security-policy"]


def test_ingest_rejects_wrong_token(client):
    with client.websocket_connect("/ws/ingest/sala-1") as ws:
        _handshake(ws, token="incorrecto")
        assert _close_code(ws) == 4401
    assert client.get("/api/sessions").json()["sessions"] == []


def test_ingest_rejects_audio_before_handshake(client):
    with client.websocket_connect("/ws/ingest/sala-1") as ws:
        ws.send_bytes(tone(0.1))
        assert _close_code(ws) == 4400


def test_ingest_rejects_invalid_session_id(client):
    with client.websocket_connect("/ws/ingest/Sala%20Uno") as ws:
        assert _close_code(ws) == 4400


def test_ingest_rejects_invalid_language(client):
    with client.websocket_connect("/ws/ingest/sala-1") as ws:
        _handshake(ws, target_lang="<script>")
        assert _close_code(ws) == 4400


def test_second_producer_is_rejected(client):
    with client.websocket_connect("/ws/ingest/sala-1") as first:
        _handshake(first)
        assert first.receive_json()["type"] == "ready"
        with client.websocket_connect("/ws/ingest/sala-1") as second:
            _handshake(second)
            assert _close_code(second) == 4409
        # La sesión original sigue viva.
        assert [s["id"] for s in client.get("/api/sessions").json()["sessions"]] == ["sala-1"]


def test_session_limit(client):
    producers = []
    try:
        for i in range(3):
            ws = client.websocket_connect(f"/ws/ingest/sala-{i}").__enter__()
            producers.append(ws)
            _handshake(ws)
            assert ws.receive_json()["type"] == "ready"
        with client.websocket_connect("/ws/ingest/sala-extra") as extra:
            _handshake(extra)
            assert _close_code(extra) == 4429
    finally:
        for ws in producers:
            ws.__exit__(None, None, None)


def test_captions_for_unknown_session(client):
    with client.websocket_connect("/ws/captions/no-existe") as ws:
        assert ws.receive_json() == {"type": "error", "error": "session_not_found"}
        assert _close_code(ws) == 4404


def test_full_flow_captions_end_and_export(client):
    with client.websocket_connect("/ws/ingest/sala-1") as producer:
        _handshake(producer, target_lang="es")
        ready = producer.receive_json()
        assert ready["type"] == "ready"
        assert ready["target_lang"] == "es"
        assert client.get("/api/sessions").json()["sessions"] == [
            {"id": "sala-1", "source_lang": "en", "target_lang": "es"}
        ]

        with client.websocket_connect("/ws/captions/sala-1?lang=es") as viewer:
            producer.send_bytes(tone(1.2))
            caption = viewer.receive_json()
            assert caption["type"] == "caption"
            assert caption["lang"] == "es"
            assert caption["text"]
            assert caption["start_s"] == 0.0

            producer.close()
            # Al terminar la sesión, el visor recibe el aviso de fin.
            while (message := viewer.receive_json())["type"] == "caption":
                pass
            assert message == {"type": "ended"}

    _wait_until_no_sessions(client)
    srt = client.get("/api/sessions/sala-1/export", params={"lang": "original", "fmt": "srt"})
    assert srt.status_code == 200
    assert srt.text.startswith("1\n00:00:00,000 --> ")
    assert 'filename="sala-1-original.srt"' in srt.headers["content-disposition"]

    vtt = client.get("/api/sessions/sala-1/export", params={"lang": "es", "fmt": "vtt"})
    assert vtt.text.startswith("WEBVTT")


def test_export_validates_input(client):
    assert client.get("/api/sessions/sala-1/export", params={"fmt": "exe"}).status_code == 400
    assert client.get("/api/sessions/sala-1/export", params={"lang": "../x"}).status_code == 400
    assert client.get("/api/sessions/NO_VALIDA/export").status_code == 400
    assert client.get("/api/sessions/inexistente/export").status_code == 404
