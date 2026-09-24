"""Configuración del backend: rutas, credenciales y parámetros del modelo."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-live-preview")

# Idioma al que se traduce en tiempo real (además de la transcripción en el
# idioma original, que siempre se genera).
TARGET_LANGUAGE = os.environ.get("TARGET_LANGUAGE", "es")

# Audio esperado por la Live API: PCM16, mono, 16 kHz, sin header WAV.
AUDIO_SAMPLE_RATE = 16000
AUDIO_MIME_TYPE = f"audio/pcm;rate={AUDIO_SAMPLE_RATE}"
