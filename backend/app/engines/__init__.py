"""Motores de transcripción/traducción intercambiables (CAPTION_ENGINE)."""
from .base import Engine, EngineError, SegmentResult

ENGINE_NAMES = ("local", "gemini", "mock")


def create_engine(name: str) -> Engine:
    # Imports diferidos: cada motor trae sus propias dependencias opcionales.
    if name == "local":
        from .local import LocalEngine

        return LocalEngine()
    if name == "gemini":
        from .gemini import GeminiEngine

        return GeminiEngine()
    if name == "mock":
        from .mock import MockEngine

        return MockEngine()
    raise EngineError(f"CAPTION_ENGINE desconocido: {name!r} (usar {', '.join(ENGINE_NAMES)})")


__all__ = ["ENGINE_NAMES", "Engine", "EngineError", "SegmentResult", "create_engine"]
