#!/usr/bin/env python3
"""Simula una fuente de audio en vivo transmitiendo un archivo al backend.

Sirve para probar/demostrar el pipeline sin necesitar un micrófono: toma
cualquier archivo de audio o video (WAV, MP3, MP4, MKV, lo que sea que
ffmpeg pueda leer — por ejemplo, la grabación de una charla), lo decodifica
a PCM16 16kHz mono y lo envía en frames al ritmo real de reproducción por
WebSocket a /ws/ingest/{session_id}, tal como llegaría el audio de un
escenario en vivo.

Si el archivo ya es un WAV 16kHz mono PCM16, se transmite directamente sin
pasar por ffmpeg (no hace falta tenerlo instalado para ese caso).

Para demostrar el requisito de sesiones concurrentes (N5), correr este
script dos veces en paralelo con --session-id distintos.

Uso:
    python tools/stream_audio_file.py sample_audio/charla1.mp4 --session-id escenario-1
    python tools/stream_audio_file.py sample_audio/charla2.wav --session-id escenario-2
"""
import argparse
import asyncio
import shutil
import wave

import websockets

SAMPLE_RATE = 16000
CHUNK_MS = 100
CHUNK_BYTES = int(SAMPLE_RATE * 2 * CHUNK_MS / 1000)  # PCM16 mono


def _is_compliant_wav(path: str) -> bool:
    try:
        with wave.open(path, "rb") as wf:
            return (
                wf.getframerate() == SAMPLE_RATE
                and wf.getnchannels() == 1
                and wf.getsampwidth() == 2
            )
    except wave.Error:
        return False


async def _pcm_chunks_from_wav(path: str):
    with wave.open(path, "rb") as wf:
        chunk_frames = int(SAMPLE_RATE * CHUNK_MS / 1000)
        while True:
            data = wf.readframes(chunk_frames)
            if not data:
                break
            yield data


async def _pcm_chunks_via_ffmpeg(path: str):
    if shutil.which("ffmpeg") is None:
        raise SystemExit(
            f"'{path}' no es un WAV 16kHz mono PCM16, y no encontré ffmpeg "
            "instalado para convertirlo al vuelo.\n"
            "Instalalo con:\n"
            "  Windows: winget install Gyan.FFmpeg\n"
            "  macOS:   brew install ffmpeg\n"
            "  Linux:   apt install ffmpeg"
        )
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-v", "error",
        "-i", path,
        "-f", "s16le",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    while True:
        data = await proc.stdout.read(CHUNK_BYTES)
        if not data:
            break
        yield data
    stderr = await proc.stderr.read()
    returncode = await proc.wait()
    if returncode != 0:
        raise SystemExit(f"ffmpeg falló procesando '{path}':\n{stderr.decode(errors='replace').strip()}")


async def stream(path: str, url: str) -> None:
    chunks = _pcm_chunks_from_wav(path) if _is_compliant_wav(path) else _pcm_chunks_via_ffmpeg(path)

    async with websockets.connect(url, max_size=None) as ws:
        print(f"Transmitiendo '{path}' a {url} ...")
        total_sent = 0
        async for data in chunks:
            await ws.send(data)
            total_sent += len(data)
            await asyncio.sleep(CHUNK_MS / 1000)
        print(f"Fin del archivo. {total_sent} bytes enviados.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio_file", help="Ruta a un archivo de audio o video")
    parser.add_argument("--session-id", required=True, help="Identificador de la sesión/escenario")
    parser.add_argument("--host", default="localhost:8000", help="host:puerto del backend")
    parser.add_argument("--secure", action="store_true", help="Usar wss:// en vez de ws://")
    args = parser.parse_args()

    scheme = "wss" if args.secure else "ws"
    url = f"{scheme}://{args.host}/ws/ingest/{args.session_id}"
    asyncio.run(stream(args.audio_file, url))


if __name__ == "__main__":
    main()
