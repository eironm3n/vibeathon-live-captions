# OpenCaption Live.
# Debian slim y no Alpine: los wheels de CTranslate2/onnxruntime que usa el
# motor local solo se publican para glibc.
FROM python:3.14.7-slim-bookworm

# Motores cuyas dependencias se instalan (separados por espacio): local, gemini.
# "mock" no necesita nada extra. docker-compose.yml lo toma de CAPTION_ENGINE.
ARG ENGINES="local"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MODELS_DIR=/models

WORKDIR /app

COPY backend/requirements*.txt backend/
RUN pip install -r backend/requirements.txt \
 && for engine in $ENGINES; do \
      if [ -f "backend/requirements-$engine.txt" ]; then pip install -r "backend/requirements-$engine.txt"; fi; \
    done

# Usuario sin privilegios; /models guarda los modelos descargados (volumen).
RUN useradd --create-home --uid 10001 opencaption \
 && mkdir -p /models \
 && chown opencaption /models

COPY backend/app backend/app
COPY frontend frontend
COPY glossary.txt glossary.txt

USER opencaption
WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
