"""Configuración común de los tests: motor mock, token fijo y segmentos cortos.

Las variables se fijan antes de importar la app porque `app.config` las lee
al importarse (y `load_dotenv` no pisa variables ya definidas).
"""
import math
import os
import struct

os.environ["CAPTION_ENGINE"] = "mock"
os.environ["INGEST_TOKEN"] = "test-token"
os.environ["SOURCE_LANGUAGE"] = "en"
os.environ["TARGET_LANGUAGE"] = "es"
os.environ["SEGMENT_MIN_SECONDS"] = "0.5"
os.environ["SEGMENT_MAX_SECONDS"] = "1"
os.environ["MAX_SESSIONS"] = "3"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

TOKEN = "test-token"
SAMPLE_RATE = 16000


def tone(seconds: float, amplitude: int = 8000, freq: float = 440.0) -> bytes:
    n = int(seconds * SAMPLE_RATE)
    return struct.pack(
        f"<{n}h", *(int(amplitude * math.sin(2 * math.pi * freq * i / SAMPLE_RATE)) for i in range(n))
    )


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(seconds * SAMPLE_RATE)


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
