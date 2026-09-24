"""Glosario de términos técnicos / nombres propios para mejorar la traducción.

Se carga una vez al importar el módulo (el glosario no cambia en caliente;
si se edita `glossary.txt` hay que reiniciar el backend).
"""
import os
from pathlib import Path

from .config import REPO_ROOT

GLOSSARY_PATH = Path(os.environ.get("GLOSSARY_PATH", REPO_ROOT / "glossary.txt"))


def _load_lines() -> list[str]:
    if not GLOSSARY_PATH.exists():
        return []
    lines = []
    for raw in GLOSSARY_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def build_glossary_instructions() -> str:
    """Devuelve un bloque de texto listo para sumar al system_instruction."""
    lines = _load_lines()
    if not lines:
        return ""

    bullets = []
    for line in lines:
        if "=>" in line:
            wrong, right = line.split("=>", 1)
            bullets.append(f'- Si te parece escuchar algo como "{wrong.strip()}", en realidad es "{right.strip()}".')
        else:
            bullets.append(f'- "{line}" se mantiene tal cual, no lo traduzcas ni lo alteres.')

    return (
        "\n\nGlosario de términos técnicos y nombres propios de esta conferencia "
        "(tiene prioridad sobre tu criterio general):\n" + "\n".join(bullets)
    )


GLOSSARY_INSTRUCTIONS = build_glossary_instructions()
