"""Configuración del backend, leída de variables de entorno (ver `.env.example`)."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = REPO_ROOT / "frontend"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# --- Motor de transcripción/traducción -------------------------------------
# local  -> Whisper + traductor offline, sin key ni costo (por defecto).
# gemini -> Gemini Live API de Google (requiere GEMINI_API_KEY).
# mock   -> texto simulado, para probar la interfaz o el overlay sin nada más.
CAPTION_ENGINE = os.environ.get("CAPTION_ENGINE", "local").strip().lower()

# Idioma en el que se habla ("auto" = que lo detecte el motor) y al que se
# traduce. Son los valores por defecto: cada sesión puede pedir otros.
SOURCE_LANGUAGE = os.environ.get("SOURCE_LANGUAGE", "en").strip().lower()
TARGET_LANGUAGE = os.environ.get("TARGET_LANGUAGE", "es").strip().lower()

# --- Seguridad -------------------------------------------------------------
# Token que necesita un productor de audio para abrir una sesión. Si no se
# define, se genera uno aleatorio en cada arranque y se muestra en el log:
# nadie puede mandar audio (y consumir recursos o la key) sin conocerlo.
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "").strip()
INGEST_TOKEN_GENERATED = not INGEST_TOKEN
if INGEST_TOKEN_GENERATED:
    INGEST_TOKEN = secrets.token_urlsafe(24)

# --- Límites -----------------------------------------------------------------
MAX_SESSIONS = _env_int("MAX_SESSIONS", 10)
# Sesiones terminadas que se conservan en memoria para exportar su transcripción.
ARCHIVE_MAX_SESSIONS = _env_int("ARCHIVE_MAX_SESSIONS", 50)
# Segmentos esperando al motor por sesión. Si el motor es más lento que el
# audio, los que excedan este número se descartan (mejor perder un segmento
# que atrasar los subtítulos sin límite).
MAX_PENDING_SEGMENTS = _env_int("MAX_PENDING_SEGMENTS", 4)
MAX_AUDIO_FRAME_BYTES = 64 * 1024
MAX_HISTORY_EVENTS = 10_000

# --- Segmentación del audio --------------------------------------------------
# Se corta un segmento en el primer silencio después de SEGMENT_MIN_SECONDS,
# o sí o sí al llegar a SEGMENT_MAX_SECONDS.
SEGMENT_MIN_SECONDS = _env_float("SEGMENT_MIN_SECONDS", 4.0)
SEGMENT_MAX_SECONDS = _env_float("SEGMENT_MAX_SECONDS", 10.0)

# Audio esperado: PCM16, mono, 16 kHz, sin header WAV.
AUDIO_SAMPLE_RATE = 16000
AUDIO_MIME_TYPE = f"audio/pcm;rate={AUDIO_SAMPLE_RATE}"

# --- Motor local -----------------------------------------------------------
MODELS_DIR = Path(os.environ.get("MODELS_DIR", REPO_ROOT / "models"))
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
# Segmentos procesados a la vez por el motor local, sumando todas las sesiones.
LOCAL_MAX_PARALLEL = _env_int("LOCAL_MAX_PARALLEL", 1)
# argos  -> modelos offline de Argos Translate (se descargan la primera vez).
# ollama -> un LLM local servido por Ollama.
# none   -> solo transcripción, sin traducción.
TRANSLATOR = os.environ.get("TRANSLATOR", "argos").strip().lower()
ARGOS_INDEX_URL = os.environ.get(
    "ARGOS_INDEX_URL",
    "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json",
)
ARGOS_AUTO_DOWNLOAD = os.environ.get("ARGOS_AUTO_DOWNLOAD", "true").lower() in {"1", "true", "yes"}
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT_SECONDS = _env_float("OLLAMA_TIMEOUT_SECONDS", 20.0)

# --- Motor Gemini ----------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-live-preview")
# Segmentos que se mandan a Gemini en paralelo por sesión (cada uno abre su
# propia conexión). Más de uno evita que los subtítulos se atrasen cuando
# Gemini tarda más que la duración del segmento.
GEMINI_MAX_PARALLEL = _env_int("GEMINI_MAX_PARALLEL", 3)
