# Audio/video de prueba

Carpeta para los archivos con los que probar el pipeline sin micrófono, ya
sea desde el panel `/admin.html` (opción *Archivo*) o con
[`tools/stream_audio_file.py`](../tools/stream_audio_file.py).

Se acepta **cualquier archivo de audio o video**. El panel web lo decodifica
en el navegador; la herramienta de terminal usa `ffmpeg` para todo lo que no
sea un WAV 16 kHz mono (`winget install Gyan.FFmpeg`, `brew install ffmpeg`
o `apt install ffmpeg`).

Los archivos de esta carpeta no se versionan (`*.wav`, `*.mp4`, etc. están
en `.gitignore`): no subas grabaciones de charlas de terceros sin permiso.

## Conseguir un clip de prueba

- **Grabate a vos mismo** unos minutos hablando del tema que quieras.
- Usá audio de **dominio público**, por ejemplo audiolibros de
  [LibriVox](https://librivox.org) (en varios idiomas).
- Grabaciones de charlas **propias**, o de eventos que te hayan dado permiso.

```bash
python tools/stream_audio_file.py sample_audio/mi_clip.mp3 --session-id prueba
```

Para probar sesiones simultáneas, corré otro archivo con otro `--session-id`
en una segunda terminal.
