"""Traductores de texto para el motor local.

- ArgosTranslator: usa los modelos abiertos de Argos Translate (CTranslate2)
  directamente, sin el paquete `argostranslate` (que arrastra PyTorch, stanza
  y spacy, varios GB). Si no hay modelo directo para un par de idiomas, se
  traduce pasando por inglés.
- OllamaTranslator: pide la traducción a un LLM local servido por Ollama.
  Suele traducir mejor, a cambio de más memoria (un modelo de 7B ronda 4-5 GB).
- NoTranslator: solo transcripción.
"""
import asyncio
import json
import logging
import shutil
import threading
import zipfile
from pathlib import Path
from typing import Protocol

import httpx

from ..glossary import GLOSSARY
from ..languages import language_name

logger = logging.getLogger(__name__)

PIVOT_LANGUAGE = "en"
MAX_PACKAGE_BYTES = 1024 * 1024 * 1024  # 1 GB: ningún paquete de Argos se acerca


class Translator(Protocol):
    name: str

    async def translate(self, pieces: list[str], source: str, target: str) -> str | None:
        """Traduce los fragmentos (en orden) y devuelve el texto completo."""
        ...


class NoTranslator:
    name = "none"

    async def translate(self, pieces: list[str], source: str, target: str) -> str | None:
        return None


class OllamaTranslator:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_seconds: float):
        self._base_url = base_url
        self._model = model
        self._timeout = timeout_seconds

    async def translate(self, pieces: list[str], source: str, target: str) -> str | None:
        text = " ".join(pieces)
        source_hint = f"del {language_name(source)} " if source != "auto" else ""
        system = (
            "Sos un traductor simultáneo para una conferencia técnica. "
            f"Traducí el texto que te paso {source_hint}al {language_name(target)}. "
            "Devolvé ÚNICAMENTE la traducción, sin comentarios, comillas ni explicaciones."
            + GLOSSARY.prompt_instructions()
        )
        payload = {
            "model": self._model,
            "stream": False,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        return str(data.get("message", {}).get("content", "")).strip() or None


class _SentencePieceTokenizer:
    def __init__(self, model_file: Path):
        import sentencepiece

        self._sp = sentencepiece.SentencePieceProcessor(model_file=str(model_file))

    def encode(self, text: str) -> list[str]:
        return self._sp.encode(text, out_type=str)

    def decode(self, tokens: list[str]) -> str:
        return self._sp.decode_pieces(tokens).replace("▁", " ")


class _BpeTokenizer:
    """Formato de los paquetes Argos más nuevos: Moses + BPE (subword-nmt)."""

    def __init__(self, codes_file: Path, source: str, target: str):
        from sacremoses import MosesDetokenizer, MosesPunctNormalizer, MosesTokenizer
        from subword_nmt.apply_bpe import BPE

        self._normalizer = MosesPunctNormalizer(source)
        self._tokenizer = MosesTokenizer(source)
        self._detokenizer = MosesDetokenizer(target)
        with codes_file.open(encoding="utf-8") as codes:
            self._bpe = BPE(codes)

    def encode(self, text: str) -> list[str]:
        tokens = self._tokenizer.tokenize(self._normalizer.normalize(text))
        return self._bpe.segment_tokens(tokens)

    def decode(self, tokens: list[str]) -> str:
        return self._detokenizer.detokenize(" ".join(tokens).replace("@@ ", "").split(" "))


class _ArgosPackage:
    def __init__(self, path: Path):
        import ctranslate2

        meta = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        self.source = meta["from_code"]
        self.target = meta["to_code"]
        self._target_prefix = meta.get("target_prefix", "")
        self._translator = ctranslate2.Translator(str(path / "model"), device="cpu", compute_type="int8")
        if (path / "sentencepiece.model").exists():
            self._tokenizer = _SentencePieceTokenizer(path / "sentencepiece.model")
        elif (path / "bpe.model").exists():
            self._tokenizer = _BpeTokenizer(path / "bpe.model", self.source, self.target)
        else:
            raise RuntimeError(f"Paquete Argos sin tokenizador reconocido: {path}")

    def translate(self, pieces: list[str]) -> list[str]:
        batch = [self._tokenizer.encode(piece) for piece in pieces]
        prefix = [[self._target_prefix]] * len(batch) if self._target_prefix else None
        results = self._translator.translate_batch(
            batch, target_prefix=prefix, beam_size=2, replace_unknowns=True
        )
        translated = []
        for result in results:
            text = self._tokenizer.decode(result.hypotheses[0]).strip()
            if self._target_prefix and text.startswith(self._target_prefix):
                text = text[len(self._target_prefix) :].strip()
            translated.append(text)
        return translated


class ArgosTranslator:
    name = "argos"

    def __init__(self, models_dir: Path, index_url: str, auto_download: bool):
        self._dir = models_dir / "argos"
        self._index_url = index_url
        self._auto_download = auto_download
        self._index: list[dict] | None = None
        self._packages: dict[tuple[str, str], _ArgosPackage] = {}
        self._lock = threading.Lock()

    async def translate(self, pieces: list[str], source: str, target: str) -> str | None:
        if source == target:
            return " ".join(pieces)
        return await asyncio.to_thread(self._translate_sync, pieces, source, target)

    def _translate_sync(self, pieces: list[str], source: str, target: str) -> str:
        for step_source, step_target in self._route(source, target):
            pieces = self._package(step_source, step_target).translate(pieces)
        return " ".join(pieces)

    def _route(self, source: str, target: str) -> list[tuple[str, str]]:
        if self._available(source, target):
            return [(source, target)]
        if PIVOT_LANGUAGE not in (source, target) and (
            self._available(source, PIVOT_LANGUAGE) and self._available(PIVOT_LANGUAGE, target)
        ):
            return [(source, PIVOT_LANGUAGE), (PIVOT_LANGUAGE, target)]
        raise RuntimeError(f"No hay modelo de Argos para traducir {source} -> {target}")

    def _package_dir(self, source: str, target: str) -> Path:
        return self._dir / f"{source}_{target}"

    def _available(self, source: str, target: str) -> bool:
        if (self._package_dir(source, target) / "metadata.json").exists():
            return True
        return self._auto_download and self._index_entry(source, target) is not None

    def _package(self, source: str, target: str) -> _ArgosPackage:
        with self._lock:
            key = (source, target)
            if key not in self._packages:
                path = self._package_dir(source, target)
                if not (path / "metadata.json").exists():
                    self._download(source, target)
                self._packages[key] = _ArgosPackage(path)
            return self._packages[key]

    def _index_entry(self, source: str, target: str) -> dict | None:
        if self._index is None:
            response = httpx.get(self._index_url, timeout=30, follow_redirects=True)
            response.raise_for_status()
            self._index = response.json()
        for entry in self._index:
            if entry.get("from_code") == source and entry.get("to_code") == target:
                return entry
        return None

    def _download(self, source: str, target: str) -> None:
        entry = self._index_entry(source, target) if self._auto_download else None
        if entry is None:
            raise RuntimeError(
                f"Falta el modelo de Argos {source}->{target} en {self._dir} "
                "(y ARGOS_AUTO_DOWNLOAD está desactivado o no existe en el índice)"
            )
        url = next((link for link in entry.get("links", []) if link.startswith("https://")), None)
        if url is None:
            raise RuntimeError(f"El índice de Argos no tiene un link https para {source}->{target}")

        logger.info("Descargando modelo de traducción %s->%s desde %s ...", source, target, url)
        self._dir.mkdir(parents=True, exist_ok=True)
        archive = self._dir / f".{source}_{target}.download"
        staging = self._dir / f".{source}_{target}.staging"
        try:
            with httpx.stream("GET", url, timeout=60, follow_redirects=True) as response:
                response.raise_for_status()
                written = 0
                with archive.open("wb") as out:
                    for chunk in response.iter_bytes():
                        written += len(chunk)
                        if written > MAX_PACKAGE_BYTES:
                            raise RuntimeError("El paquete de Argos excede el tamaño máximo esperado")
                        out.write(chunk)
            shutil.rmtree(staging, ignore_errors=True)
            _safe_extract(archive, staging)
            package_root = next(p.parent for p in staging.rglob("metadata.json"))
            shutil.move(str(package_root), str(self._package_dir(source, target)))
            logger.info("Modelo de traducción %s->%s instalado", source, target)
        finally:
            archive.unlink(missing_ok=True)
            shutil.rmtree(staging, ignore_errors=True)


def _safe_extract(archive: Path, destination: Path) -> None:
    """Extrae el zip validando que ninguna entrada escape de `destination` (zip slip).

    Se omiten los modelos de stanza que traen los paquetes: solo los usa
    `argostranslate` para cortar oraciones, y acá Whisper ya entrega el texto
    separado en frases.
    """
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            if "/stanza/" in f"/{member.filename}":
                continue
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination):
                raise RuntimeError(f"Entrada sospechosa en el paquete de Argos: {member.filename}")
            zf.extract(member, destination)
