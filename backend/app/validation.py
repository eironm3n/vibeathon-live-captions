"""Validación de identificadores que llegan desde afuera (URL, query, mensajes)."""
import re

# Minúsculas, números, guion y guion bajo: seguro para URLs, logs y nombres
# de archivo (el id termina en el Content-Disposition de la exportación).
SESSION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Código de idioma corto: "es", "en", "pt", "pt-br"...
LANG_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})?$")


def is_valid_session_id(value: str) -> bool:
    return bool(SESSION_ID_RE.match(value))


def is_valid_lang(value: str) -> bool:
    return bool(LANG_RE.match(value))


def is_valid_source_lang(value: str) -> bool:
    return value == "auto" or is_valid_lang(value)
