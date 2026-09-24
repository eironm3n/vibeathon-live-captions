# OpenCaption Live

Transcripción y traducción simultánea en tiempo real para conferencias,
pensada para reemplazar herramientas comerciales caras y operación manual
por un pipeline automático, abierto y replicable por cualquier evento.

Construido por [Aron Rojas](https://github.com/eironm3n) para la
[Vibeathon de Nerdearla 2026](https://nerdear.la).

## El problema

Nerdearla (y casi toda conferencia) resuelve hoy la accesibilidad de sus
charlas con herramientas comerciales de transcripción/traducción y
operación manual. Con 30+ sesiones en inglés en simultáneo, ese esquema no
escala: es caro y depende de gente operándolo en vivo. El objetivo de este
proyecto no es reemplazar intérpretes humanos en todo contexto, sino dar
una alternativa abierta y barata para cuando esa opción no está disponible.

## Necesidades que cubre (alcance MVP)

| # | Necesidad | Cómo se resuelve |
|---|-----------|-------------------|
| N1 | Ingesta de audio en vivo | WebSocket `/ws/ingest/{session_id}` acepta frames PCM16 16kHz mono desde cualquier fuente (mic, archivo, stream). Incluye [`tools/stream_audio_file.py`](tools/stream_audio_file.py) para simular una fuente en vivo desde un archivo. |
| N2 | Transcripción en tiempo real (idioma original) | `input_audio_transcription` de la Gemini Live API, sobre el audio que llega a cada sesión. |
| N3 | Traducción en tiempo real EN→ES (y cualquier idioma→destino) | La misma conexión Live API traduce el audio al idioma destino (`TARGET_LANGUAGE`, por defecto `es`) vía `system_instruction`. |
| N4 | Visualización de subtítulos | Vista web de audiencia ([`frontend/`](frontend/)) que se conecta por WebSocket a `/ws/captions/{session_id}` y muestra el texto en vivo. |
| N5 | Múltiples sesiones en simultáneo | Cada sesión (`session_id`) corre de forma independiente — su propia conexión Gemini Live y su propio canal de subtítulos. No hay límite artificial: correr 2, 5 o 10 sesiones es simplemente usar 2, 5 o 10 `session_id` distintos. Ver [Escalar a más sesiones](#escalar-a-más-sesiones). |

## Opcionales implementados

| Opcional | Cómo se resuelve |
|---|---|
| Integración con OBS/vMix | [`/overlay.html`](frontend/overlay.html) — vista con fondo transparente y sin controles, pensada para usarse directo como *Browser Source*. `http://localhost:8000/overlay.html?session=escenario-1&lang=es` |
| Exportar transcripción (SRT/VTT/texto) | `GET /api/sessions/{session_id}/export?lang=original\|es&fmt=srt\|vtt\|txt` — funciona con la sesión activa o ya terminada. Cada subtítulo final se guarda con su timestamp real (relativo al audio, no al momento en que Gemini respondió), así el archivo queda sincronizado. Desde el frontend, los links `.srt` / `.vtt` del header apuntan a la sesión y el idioma seleccionados. |
| Glosario de términos técnicos / nombres propios | [`glossary.txt`](glossary.txt) en la raíz del repo: una entrada por línea, `término` (se mantiene tal cual) o `mal_reconocido => correcto` (corrige errores típicos de reconocimiento). Se inyecta en el `system_instruction` de la traducción. Se recarga solo al reiniciar el backend. |

Quedan para una siguiente etapa (documentados pero no implementados): más
idiomas de entrada/salida seleccionables por la audiencia (el backend ya
soporta cualquier idioma vía `TARGET_LANGUAGE`, pero hoy es uno por
despliegue, no por sesión) y un panel de monitoreo de producción.

## Arquitectura

```
productor de audio          backend (FastAPI)                visor
(mic / archivo / stream) ─▶ /ws/ingest/{id} ─▶ GeminiBridge ─▶ Gemini Live API
                                   │                                │
                                   │        transcripción(N2) + traducción(N3)
                                   ▼                                │
                              CaptionHub  ◀──────────────────────────
                                   │
                                   ▼
                          /ws/captions/{id} ─▶ frontend (vista de audiencia)
```

- `backend/app/gemini_bridge.py`: agrupa el audio de una sesión en
  segmentos, abre una conexión Gemini Live por segmento y traduce las
  respuestas del modelo en eventos de subtítulo (usa el glosario de
  `glossary.py`).
- `backend/app/session_manager.py`: registro de sesiones activas + archivo
  de sesiones terminadas (para poder exportarlas después).
- `backend/app/caption_hub.py`: pub/sub en memoria que reparte los
  subtítulos de una sesión a todos sus visores conectados, y guarda el
  historial de subtítulos finales para exportar.
- `backend/app/export.py`: arma SRT/VTT/texto a partir de ese historial.
- `backend/app/glossary.py`: carga `glossary.txt` (raíz del repo) para
  mejorar la traducción de términos técnicos y nombres propios.
- `frontend/`: página estática sin build step — selector de sesión +
  toggle de idioma + panel de subtítulos + links de overlay/export.
- `frontend/overlay.html` + `overlay.js`: vista minimal para usar como
  Browser Source en OBS/vMix.

## Requisitos

- Una API key de [Google AI Studio](https://aistudio.google.com/) con
  acceso a la Gemini Live API (necesita un proyecto de Google Cloud
  asociado a tu cuenta — si el desplegable de proyectos aparece vacío al
  crear la key, creá uno primero en
  [console.cloud.google.com/projectcreate](https://console.cloud.google.com/projectcreate),
  no hace falta activar billing).
- Docker + Docker Compose (recomendado), o Python 3.12+ para correrlo local.
- `ffmpeg` instalado, si vas a probar con un archivo que no sea ya un WAV
  16kHz mono PCM16 (por ejemplo, cualquier video). `winget install
  Gyan.FFmpeg` (Windows) / `brew install ffmpeg` (macOS) / `apt install
  ffmpeg` (Linux).

## Cómo levantarlo

### Con Docker (recomendado)

```bash
cp .env.example .env
# editá .env y poné tu GEMINI_API_KEY

docker compose up --build
```

La vista de audiencia queda en `http://localhost:8000`.

### Local, sin Docker

```bash
cp .env.example .env
# editá .env y poné tu GEMINI_API_KEY

cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Cómo probarlo

El backend no genera audio por sí solo: necesita que algo le mande frames
de audio a `/ws/ingest/{session_id}`. Para probarlo sin depender de un
micrófono, usamos un archivo de prueba — puede ser video o audio, en
cualquier formato que `ffmpeg` sepa leer (ver
[`sample_audio/README.md`](sample_audio/README.md) para conseguir uno, por
ejemplo la grabación de una charla):

```bash
python tools/stream_audio_file.py sample_audio/mi_charla.mp4 --session-id escenario-1
```

Abrí `http://localhost:8000`, elegí `escenario-1` en el selector y mirá los
subtítulos en vivo.

Para demostrar el requisito N5 (sesiones concurrentes), abrí otra terminal
y corré un segundo archivo con otro `session_id`:

```bash
python tools/stream_audio_file.py sample_audio/otra_charla.mp4 --session-id escenario-2
```

Las dos sesiones corren en paralelo y son seleccionables por separado en
el frontend.

## Escalar a más sesiones

El diseño actual soporta N sesiones concurrentes dentro de un mismo
proceso (cada una es una tarea `asyncio` independiente). Para escalar más
allá de la capacidad de una sola instancia:

- Correr varias réplicas de este mismo contenedor detrás de un balanceador
  con *sticky routing* por `session_id` (el productor y los visores de una
  sesión deben llegar siempre a la misma réplica).
- Si se necesita descubrir en qué réplica vive cada sesión, mover el
  registro de `session_manager.py` a un almacén compartido (por ejemplo
  Redis) en vez de un dict en memoria.

## Estado / limitaciones conocidas

Probado de punta a punta contra la Gemini Live API real (`gemini-3.1-flash-live-preview`,
el único modelo "Live" disponible en la cuenta usada para probar — si tu
cuenta tiene otro, cambiá `GEMINI_MODEL`), incluyendo dos sesiones
concurrentes reales. En el camino aparecieron un par de límites del modelo
que moldearon el diseño de `gemini_bridge.py`:

- **Una conexión Live solo responde a un turno.** Se probó mantener una
  única conexión abierta durante toda la sesión (como sería lo más
  natural), pero ni la detección automática de silencio ni
  `activity_start`/`activity_end` manuales dispararon una segunda
  respuesta en la misma conexión — hacía falta abrir una conexión nueva
  por turno. Por eso el audio se junta en segmentos de `SEGMENT_SECONDS`
  (8s por defecto) y cada segmento abre su propia conexión corta. Esto
  agrupa los subtítulos en bloques de unos segundos en vez de palabra por
  palabra — es la principal oportunidad de mejora si aparece un modelo/API
  que soporte múltiples turnos por conexión.
- **El modelo no soporta salida solo-texto** (`response_modalities=["TEXT"]`
  falla). Hay que pedir audio (`["AUDIO"]`) y leer la transcripción de esa
  salida (`output_audio_transcription`), descartando el audio en sí. Esto
  agrega latencia: el modelo genera el audio completo de la traducción
  antes de poder devolver su transcripción (en las pruebas, un segmento de
  ~8s tardó bastante más que 8s en resolverse).
- El WebSocket de subtítulos rechaza la conexión si la sesión todavía no
  existe (el productor de audio debe conectarse antes que el visor).

### Oportunidad de mejora: latencia

`gemini-3.5-transcribe-live` y `gemini-3.5-live-translate-preview` son
modelos especializados que sí aceptan `response_modalities=["TEXT"]`, y
este último tiene un `translation_config.target_language_code` hecho a
medida para traducir sin tener que instruir al modelo por prompt — en
teoría evitarían por completo la generación de audio innecesaria y
bajarían mucho la latencia. Al probarlos con audio real fallaron con
`1008 policy violation: operation was aborted` (probablemente límites de
uso más estrictos por ser preview, agravado por la cantidad de pruebas ya
hechas contra la cuenta). Vale la pena reintentarlos con más margen antes
de la entrega final.

## Troubleshooting

- **`models/... is not found ... bidiGenerateContent`** al arrancar una
  sesión: tu cuenta no tiene el modelo de `GEMINI_MODEL` (varía por cuenta
  / región). Listá los modelos Live disponibles para tu key y elegí uno:
  ```bash
  python -c "
  from google import genai
  import os
  client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
  for m in client.models.list():
      if 'bidiGenerateContent' in (m.supported_actions or []):
          print(m.name)
  "
  ```
  y poné el que elijas en `GEMINI_MODEL` (en `.env`).
- **`No API key was provided`** o el WebSocket de ingesta se cierra con
  código 1011 apenas conecta: falta `GEMINI_API_KEY` en `.env`, o está mal
  copiada.

## Autor

**Aron Rojas** — [github.com/eironm3n](https://github.com/eironm3n)

## Licencia

MIT — ver [LICENSE](LICENSE).
