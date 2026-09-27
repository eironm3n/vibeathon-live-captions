# OpenCaption Live

Subtítulos y traducción simultánea en tiempo real para conferencias, abierto
y replicable por cualquier evento. Transcribe lo que se dice en cada sala, lo
traduce al idioma del público y lo muestra en una vista web o como overlay
en OBS/vMix, con la transcripción completa exportable a SRT/VTT.

Por defecto funciona **sin API keys, sin costo y sin que el audio salga de
la máquina** (Whisper + traducción offline). Opcionalmente puede usar la
Gemini Live API de Google.

## Origen

Este proyecto nació como una **propuesta para la Vibeathon de
[Nerdearla](https://nerdear.la) 2026**, una hackatón de 24 horas. No llegó a
entregarse a tiempo, así que se terminó y se publica como proyecto
independiente de código abierto, manteniendo la idea original: que la
accesibilidad de una conferencia no dependa de herramientas comerciales
caras ni de gente operándolas a mano.

No está afiliado ni avalado por Nerdearla. El nombre del evento aparece solo
para contar de dónde salió la idea.

## El problema

Casi toda conferencia resuelve hoy la accesibilidad de sus charlas con
herramientas comerciales de transcripción/traducción y operación manual. Con
muchas sesiones en simultáneo, ese esquema no escala: es caro y depende de
gente operándolo en vivo. El objetivo no es reemplazar a intérpretes humanos
en todo contexto, sino dar una alternativa abierta y barata para cuando esa
opción no está disponible.

## Qué hace

| # | Necesidad (del desafío original) | Cómo se resuelve |
|---|---|---|
| N1 | Ingesta de audio en vivo | Micrófono desde el navegador ([`/admin.html`](frontend/admin.html)), un archivo de audio/video, o cualquier fuente que mande PCM16 16 kHz por WebSocket. |
| N2 | Transcripción en tiempo real | Whisper local ([faster-whisper](https://github.com/SYSTRAN/faster-whisper)) o Gemini Live. |
| N3 | Traducción en tiempo real | Argos Translate u Ollama (locales), o Gemini. Idiomas elegibles por sesión. |
| N4 | Visualización de subtítulos | Vista de audiencia web con selector de sesión e idioma. |
| N5 | Múltiples sesiones en simultáneo | Cada sala es una sesión independiente con su propio canal de subtítulos (hasta `MAX_SESSIONS`). |
| + | Integración con OBS/vMix | [`/overlay.html`](frontend/overlay.html): fondo transparente, se reconecta sola entre charlas. |
| + | Exportar la transcripción | SRT, VTT o texto, con tiempos relativos al audio, de sesiones activas o terminadas. |
| + | Glosario técnico | [`glossary.txt`](glossary.txt): términos que no se traducen y correcciones de reconocimiento. |

## Motores

| Motor | Qué usa | Key | Costo | Privacidad | Cuándo conviene |
|---|---|---|---|---|---|
| `local` (por defecto) | Whisper + Argos Translate (u Ollama) | No | $0 | El audio no sale de la máquina | Casi siempre. |
| `gemini` | Gemini Live API | Sí | Plan gratuito limitado, o pago | El audio va a Google (ver abajo) | Sin CPU/GPU disponible. |
| `mock` | Frases simuladas | No | $0 | No procesa audio | Probar la interfaz, el overlay o los tests. |

Para traducir, el motor local ofrece:

- **`argos`** (por defecto): modelos offline de [Argos Translate](https://github.com/argosopentech/argos-translate)
  (~90–300 MB por par de idiomas, se descargan la primera vez). Rápido y
  liviano. Si no hay modelo directo entre dos idiomas, pasa por inglés.
- **`ollama`**: un LLM local vía [Ollama](https://ollama.com) (por defecto
  `qwen2.5:7b`, licencia Apache 2.0). Suele traducir mejor, a cambio de ~4–5 GB.
- **`none`**: solo transcripción.

## Arranque rápido

Requisitos: [Docker](https://docs.docker.com/get-docker/) (Docker Desktop en
Windows/macOS) corriendo. La primera vez el motor local descarga ~550 MB de
modelos.

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File .\iniciar.ps1
```

**Linux / macOS / Git Bash:**
```bash
bash iniciar.sh
```

El script crea `.env` (con un token aleatorio), levanta el contenedor y
muestra las URLs y el token. Opciones:

| Objetivo | Windows | Linux/macOS |
|---|---|---|
| Motor local (default) | `.\iniciar.ps1` | `bash iniciar.sh` |
| Probar la interfaz sin procesar audio | `.\iniciar.ps1 -Motor mock` | `bash iniciar.sh --motor mock` |
| Traducción con Ollama | `.\iniciar.ps1 -ConOllama` | `bash iniciar.sh --con-ollama` |
| Gemini (poné `GEMINI_API_KEY` en `.env`) | `.\iniciar.ps1 -Motor gemini` | `bash iniciar.sh --motor gemini` |

### Sin scripts

```bash
cp .env.example .env        # y completá INGEST_TOKEN
docker compose up -d --build
# con Ollama: docker compose -f docker-compose.yml -f docker-compose.ollama.yml up -d --build
```

### Sin Docker (Python 3.12)

```bash
cp .env.example .env
cd backend
pip install -r requirements-local.txt     # o requirements-gemini.txt / requirements.txt (mock)
uvicorn app.main:app
```

## Uso

1. **Emitir**: abrí `http://localhost:8000/admin.html`, pegá el token,
   elegí un nombre de sesión (por ejemplo `sala-principal`), los idiomas y
   la fuente (micrófono o archivo), y tocá *Iniciar transmisión*.
   También se puede emitir un archivo desde la terminal:
   ```bash
   python tools/stream_audio_file.py mi_charla.mp4 --session-id sala-principal
   ```
   (toma el token de `.env`; para archivos que no sean WAV 16 kHz mono necesita `ffmpeg`).
2. **Ver**: `http://localhost:8000`, elegí la sesión y el idioma.
3. **OBS/vMix**: agregá una *Browser Source* con
   `http://localhost:8000/overlay.html?session=sala-principal&lang=es`
   (`lang=original` para el idioma hablado).
4. **Exportar**: los links `.srt` / `.vtt` de la vista, o
   `GET /api/sessions/{id}/export?lang=original|es&fmt=srt|vtt|txt`.
   Se conservan las últimas `ARCHIVE_MAX_SESSIONS` sesiones terminadas, en
   memoria: exportá al terminar cada charla si las querés guardar.

**Glosario:** una entrada por línea en [`glossary.txt`](glossary.txt):
`término` (se mantiene tal cual) o `mal_reconocido => correcto`. Se aplica
al reiniciar el servidor.

## Arquitectura

```
emisor (mic / archivo / stream)                                   visores
        │ WS /ws/ingest/{id}  (token + PCM16 16 kHz)                  ▲
        ▼                                                             │ WS /ws/captions/{id}
  SegmentPipeline ──corta en pausas──▶ motor (local | gemini | mock)  │
        │                              transcribe + traduce           │
        └──────── publica en orden ──▶ CaptionHub ────────────────────┘
                                           └──▶ historial ──▶ /export (SRT/VTT/txt)
```

- [`backend/app/pipeline.py`](backend/app/pipeline.py): junta el audio y lo
  corta en la primera pausa después de `SEGMENT_MIN_SECONDS` (o al llegar a
  `SEGMENT_MAX_SECONDS`), procesa segmentos en paralelo y publica en orden.
  Si el motor no da abasto, descarta segmentos en vez de atrasarse sin límite.
- [`backend/app/engines/`](backend/app/engines/): los motores intercambiables.
- [`backend/app/session_manager.py`](backend/app/session_manager.py): sesiones
  activas (un emisor por sesión) y archivo de sesiones terminadas.
- [`backend/app/caption_hub.py`](backend/app/caption_hub.py): reparte los
  subtítulos a los visores y avisa cuando la sesión termina.
- [`frontend/`](frontend/): páginas estáticas sin build step.

Para escalar más allá de una máquina: varias réplicas detrás de un
balanceador con *sticky routing* por `session_id`, o mover el registro de
sesiones a un almacén compartido (Redis).

## Seguridad y privacidad

- **Emitir requiere token** (`INGEST_TOKEN`). Viaja en el primer mensaje del
  WebSocket, nunca en la URL, para que no quede en logs. Si no lo definís,
  se genera uno por arranque y se muestra en el log.
- **Un emisor por sesión**: nadie puede meter audio en una sesión ajena.
- **Límites**: sesiones simultáneas, tamaño de cada frame de audio, cola de
  segmentos, historial y sesiones archivadas.
- **Ver y exportar es público**, porque es su propósito. Si una charla es
  privada, no expongas el servidor o ponelo detrás de un proxy con login.
- **Headers de seguridad** (CSP, `nosniff`, sin referrer) en todas las páginas.
- **Por defecto solo escucha en `127.0.0.1`.** Ver [Publicarlo](#publicarlo).
- **Privacidad según el motor**: con `local`, el audio no sale de la
  máquina. Con `gemini`, el audio se envía a Google; según los términos de
  la Gemini API, lo enviado con el plan gratuito puede usarse para mejorar
  sus productos. Avisá a los oradores si usás este motor.

Para reportar una vulnerabilidad, ver [SECURITY.md](SECURITY.md).

### Publicarlo

Para usarlo desde otras máquinas (proyector, OBS en otra PC, el público):

1. Ponelo detrás de un proxy con HTTPS. El micrófono del navegador solo
   funciona en `https://` o en `localhost`. Ejemplo con [Caddy](https://caddyserver.com),
   que maneja certificados y WebSockets solo:
   ```
   subtitulos.tu-dominio.com {
       reverse_proxy 127.0.0.1:8000
   }
   ```
2. Usá un `INGEST_TOKEN` largo y fijo en `.env`, y compartilo solo con
   quien opera el audio.
3. Si necesitás exponerlo en la red local sin proxy, cambiá el puerto en
   `docker-compose.yml` a `"8000:8000"`, sabiendo que queda sin HTTPS.

## Rendimiento y limitaciones

- **Motor local**: con `WHISPER_MODEL=small` en un CPU de escritorio de 12
  hilos, 8 s de audio se transcriben en ~3 s y la traducción de Argos tarda
  milisegundos. Los subtítulos llegan ~4–5 s después de cada frase. Para
  varias salas a la vez conviene `base`, GPU (`WHISPER_DEVICE=cuda`, fuera
  de Docker) o más réplicas.
- **Fijá el idioma hablado** (`SOURCE_LANGUAGE`): la detección automática
  se confunde con acentos fuertes en fragmentos cortos.
- **Calidad**: Whisper `small` comete errores con acentos marcados o audio
  ruidoso; `medium` mejora a costa de velocidad. Argos traduce bien frases
  simples y peor las largas o técnicas; Ollama suele ser mejor. El glosario
  ayuda con nombres propios.
- **Gemini**: cada segmento abre su propia conexión (con
  `gemini-3.1-flash-live-preview` una conexión solo respondía un turno) y el
  modelo genera audio antes de devolver texto, lo que agrega latencia; por
  eso se procesan varios segmentos en paralelo (`GEMINI_MAX_PARALLEL`). Los
  modelos *preview* pueden cambiar o desaparecer.
- Los subtítulos llegan por frase, no palabra por palabra.

## Desarrollo

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

Los tests usan el motor `mock`: no necesitan key, modelos ni red. CI corre
los tests y construye la imagen Docker en cada PR; Dependabot propone las
actualizaciones de dependencias (todas con versión fijada).

## Problemas comunes

| Síntoma | Solución |
|---|---|
| El panel dice "Token inválido" | Usá el `INGEST_TOKEN` de `.env` (o el del log, si no definiste uno). |
| "Ya hay otro emisor conectado a esa sesión" | Cada sesión admite un emisor: cerrá el otro o usá otro nombre. |
| El micrófono no arranca | Tiene que ser `https://` o `localhost`, y el navegador tiene que tener permiso. |
| Los primeros subtítulos tardan mucho | La primera vez se descargan los modelos: mirá `docker compose logs -f`. |
| Subtítulos atrasados o "motor saturado" en el log | El motor no da abasto: probá `WHISPER_MODEL=base`, menos salas o GPU. |
| Gemini: `models/... is not found` | Tu cuenta no tiene ese modelo: cambiá `GEMINI_MODEL`. |

## Licencias de terceros

El código es MIT. Los modelos se descargan aparte y tienen sus propias
licencias: Whisper (MIT, OpenAI; conversión de SYSTRAN), los paquetes de
Argos Translate (ver la licencia de cada paquete) y el modelo de Ollama que
elijas (por defecto Qwen2.5 7B, Apache 2.0). Si usás Gemini, aplican los
términos de Google.

## Autor

**Aron Rojas** — [github.com/eironm3n](https://github.com/eironm3n)

<sub>Herramienta planificada y desarrollada en conjunto con Claude (Anthropic): Claude Sonnet 5 en la versión original para la Vibeathon y Claude Opus 5.5 en esta revisión.</sub>

## Licencia

MIT — ver [LICENSE](LICENSE).
