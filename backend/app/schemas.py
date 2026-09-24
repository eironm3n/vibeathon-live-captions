"""Modelos de datos compartidos entre el backend y el frontend."""
import time

from pydantic import BaseModel, Field


class CaptionEvent(BaseModel):
    """Un fragmento de subtítulo para una sesión, en un idioma dado."""

    session_id: str
    lang: str  # "original" (idioma tal cual se habló) o el código del idioma destino (ej. "es")
    text: str
    is_final: bool
    ts: float = Field(default_factory=time.time)
