"""
Prompt loading with shared placeholders.

A prompt file may contain {{NAME}} placeholders; they are filled from PLACEHOLDERS
when the prompt is loaded. An unknown placeholder raises, so a typo in a prompt
fails loudly instead of being sent to the model verbatim.
"""
import re
from collections.abc import Callable
from pathlib import Path

from app.shared.industries import render_industries

PLACEHOLDERS: dict[str, Callable[[], str]] = {
    "INDUSTRIES": render_industries,
}

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


def load_prompt(path: Path) -> str:
    """Read a prompt file and substitute its {{PLACEHOLDER}}s."""
    text = path.read_text(encoding="utf-8")

    def _fill(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in PLACEHOLDERS:
            raise ValueError(f"{path.name}: unknown prompt placeholder {{{{{name}}}}}")
        return PLACEHOLDERS[name]()

    return _PLACEHOLDER.sub(_fill, text)
