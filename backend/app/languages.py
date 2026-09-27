"""Nombres de idiomas para armar instrucciones de traducción legibles."""

_LANGUAGE_NAMES = {
    "es": "español",
    "en": "inglés",
    "pt": "portugués",
    "fr": "francés",
    "it": "italiano",
    "de": "alemán",
}


def language_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code.split("-")[0], code)
