"""Glosario de términos técnicos / nombres propios para mejorar la transcripción y la traducción.

Se carga una vez al importar el módulo (el glosario no cambia en caliente;
si se edita `glossary.txt` hay que reiniciar el backend).

Cada motor lo aprovecha como puede:
  - Gemini y el traductor Ollama lo reciben como instrucciones en el prompt.
  - Whisper recibe los términos como `hotwords` (sesga el reconocimiento).
  - Las correcciones `mal => bien` se aplican además como reemplazo directo
    sobre la transcripción, antes de traducir.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import REPO_ROOT

GLOSSARY_PATH = Path(os.environ.get("GLOSSARY_PATH", REPO_ROOT / "glossary.txt"))


@dataclass
class Glossary:
    keep: list[str] = field(default_factory=list)  # términos que no se traducen
    corrections: list[tuple[str, str]] = field(default_factory=list)  # (mal reconocido, correcto)

    @classmethod
    def parse(cls, text: str) -> "Glossary":
        glossary = cls()
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=>" in line:
                wrong, right = (part.strip() for part in line.split("=>", 1))
                if wrong and right:
                    glossary.corrections.append((wrong, right))
            else:
                glossary.keep.append(line)
        return glossary

    def prompt_instructions(self) -> str:
        """Bloque de texto listo para sumar a las instrucciones de un LLM."""
        bullets = [
            f'- Si te parece escuchar algo como "{wrong}", en realidad es "{right}".'
            for wrong, right in self.corrections
        ]
        bullets += [f'- "{term}" se mantiene tal cual, no lo traduzcas ni lo alteres.' for term in self.keep]
        if not bullets:
            return ""
        return (
            "\n\nGlosario de términos técnicos y nombres propios de esta conferencia "
            "(tiene prioridad sobre tu criterio general):\n" + "\n".join(bullets)
        )

    def hotwords(self) -> str | None:
        terms = self.keep + [right for _, right in self.corrections]
        unique = list(dict.fromkeys(terms))
        return " ".join(unique) or None

    def apply_corrections(self, text: str) -> str:
        for wrong, right in self.corrections:
            text = re.sub(rf"\b{re.escape(wrong)}\b", right, text, flags=re.IGNORECASE)
        return text


def load_glossary(path: Path = GLOSSARY_PATH) -> Glossary:
    if not path.exists():
        return Glossary()
    return Glossary.parse(path.read_text(encoding="utf-8"))


GLOSSARY = load_glossary()
