#!/usr/bin/env python3
"""Simula una fuente de audio en vivo transmitiendo un archivo al backend.

Sirve para probar/demostrar el pipeline sin necesitar un micrófono: toma
cualquier archivo de audio o video (WAV, MP3, MP4, MKV, lo que sea que
ffmpeg pueda leer), lo decodifica a PCM16 16kHz mono y lo envía en frames
al ritmo real de reproducción por WebSocket a /ws/ingest/{session_id}, tal
como llegaría el audio de un escenario en vivo.

Si el archivo ya es un WAV 16kHz mono PCM16, se transmite directamente sin
pasar por ffmpeg (no hace falta tenerlo instalado para ese caso).

El token de ingesta se toma de --token, de la variable INGEST_TOKEN o, si
no, del archivo .env en la raíz del repo.

Uso:
    python tools/stream_audio_file.py sample_audio/charla1.mp4 --session-id escenario-1
    python tools/stream_audio_file.py charla2.wav --session-id escenario-2 --target-lang pt
"""
import argparse
import asyncio
import json
import os
import shutil
import wave
from pathlib import Path

import websockets

SAMPLE_RATE = 16000
CHUNK_MS = 100
CHUNK_BYTES = int(SAMPLE_RATE * 2 * CHUNK_MS / 1000)  # PCM16 mono
REPO_ROOT = Path(__file__).resolve().parent.parent

CLOSE_REASONS = {
    4400: "pedido inválido",
    4401: "token inválido (revisá INGEST_TOKEN)",
    4409: "ya hay otro emisor conectado a esa sesión",
    4429: "el servidor alcanzó el máximo de sesiones simultáneas",
}


def _token_from_env_file() -> str | None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "INGEST_TOKEN":
            return value.strip().strip('"').strip("'") or None
    return None


def _is_compliant_wav(path: str) -> bool:
    try:
        with wave.open(path, "rb") as wf:
            return (
                wf.getframerate() == SAMPLE_RATE
                and wf.getnchannels() == 1
                and wf.getsampwidth() == 2
            )
    except (wave.Error, EOFError):
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
        if len(data) % 2:  # el servidor exige frames PCM16 completos
            data += await proc.stdout.read(1)
        yield data
    stderr = await proc.stderr.read()
    returncode = await proc.wait()
    if returncode != 0:
        raise SystemExit(f"ffmpeg falló procesando '{path}':\n{stderr.decode(errors='replace').strip()}")


async def stream(path: str, url: str, handshake: dict) -> None:
    chunks = _pcm_chunks_from_wav(path) if _is_compliant_wav(path) else _pcm_chunks_via_ffmpeg(path)

    try:
        async with websockets.connect(url, max_size=None) as ws:
            await ws.send(json.dumps(handshake))
            ready = json.loads(await ws.recv())
            print(
                f"Sesión '{ready['id']}' lista (motor {ready['engine']}, "
                f"{ready['source_lang']} -> {ready['target_lang']}). Transmitiendo '{path}'..."
            )
            total_sent = 0
            async for data in chunks:
                await ws.send(data)
                total_sent += len(data)
                await asyncio.sleep(CHUNK_MS / 1000)
            print(f"Fin del archivo. {total_sent} bytes enviados.")
    except websockets.ConnectionClosed as exc:
        code = exc.rcvd.code if exc.rcvd else None
        reason = CLOSE_REASONS.get(code, exc.rcvd.reason if exc.rcvd else "conexión cerrada")
        raise SystemExit(f"El servidor cerró la conexión ({code}): {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio_file", help="Ruta a un archivo de audio o video")
    parser.add_argument("--session-id", required=True, help="Identificador de la sesión (a-z, 0-9, - y _)")
    parser.add_argument("--host", default="localhost:8000", help="host:puerto del backend")
    parser.add_argument("--secure", action="store_true", help="Usar wss:// en vez de ws://")
    parser.add_argument("--token", help="Token de ingesta (por defecto: INGEST_TOKEN o .env)")
    parser.add_argument("--source-lang", help="Idioma hablado (ej. en, o auto). Por defecto, el del servidor")
    parser.add_argument("--target-lang", help="Idioma de la traducción (ej. es). Por defecto, el del servidor")
    args = parser.parse_args()

    token = args.token or os.environ.get("INGEST_TOKEN") or _token_from_env_file()
    if not token:
        raise SystemExit(
            "Falta el token de ingesta: pasalo con --token, o definí INGEST_TOKEN en .env "
            "(si el servidor lo generó solo, está en su log al arrancar)."
        )

    handshake = {"token": token}
    if args.source_lang:
        handshake["source_lang"] = args.source_lang
    if args.target_lang:
        handshake["target_lang"] = args.target_lang

    scheme = "wss" if args.secure else "ws"
    url = f"{scheme}://{args.host}/ws/ingest/{args.session_id}"
    asyncio.run(stream(args.audio_file, url, handshake))


if __name__ == "__main__":
    main()
