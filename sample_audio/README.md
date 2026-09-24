# Audio/video de prueba

Esta carpeta es donde poner los archivos usados para probar el pipeline con
[`tools/stream_audio_file.py`](../tools/stream_audio_file.py).

La herramienta acepta **cualquier archivo de audio o video** que `ffmpeg`
pueda leer (WAV, MP3, MP4, MKV, etc.) — no hace falta convertirlo a mano,
la conversión a PCM16 16kHz mono se hace al vuelo. Necesitás tener
`ffmpeg` instalado (`ffmpeg -version` para chequear):

- Windows: `winget install Gyan.FFmpeg`
- macOS: `brew install ffmpeg`
- Linux: `apt install ffmpeg`

No versionamos audio/video de charlas de terceros en este repo (derechos
de autor) — por eso `*.mp4`, `*.wav`, etc. están en `.gitignore`.

## Conseguir un clip de prueba

Con la grabación de una charla que ya tengas localmente, alcanza con:

```bash
python tools/stream_audio_file.py sample_audio/mi_charla.mp4 --session-id escenario-1
```

Si preferís bajar un fragmento de una charla de Nerdearla en YouTube:

```bash
pip install yt-dlp   # solo para esto, no es una dependencia del proyecto
yt-dlp -o "sample_audio/charla1.mp4" <URL>
python tools/stream_audio_file.py sample_audio/charla1.mp4 --session-id escenario-1
```

Para probar sesiones concurrentes (requisito N5), repetí con otro archivo
y otro `--session-id` en una segunda terminal.
