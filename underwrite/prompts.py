"""Versioned prompt files: prompts/<version>/<name>.md, with the system and user parts split by a
`---USER---` line and `{{var}}` placeholders. The Coach writes new versions; nothing else edits them."""

from __future__ import annotations

import re

from .config import settings

SPLIT = "---USER---"
NAMES = ["planner", "replanner", "extractor", "verifier", "writer", "analyst", "skeptic"]


def load(name: str, version: str | None = None) -> tuple[str, str]:
    version = version or settings.prompts_version
    path = settings.prompts_dir / version / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    if SPLIT not in text:
        raise ValueError(f"{path} is missing the {SPLIT} separator")
    system, user = text.split(SPLIT, 1)
    return system.strip(), user.strip()


def render(template: str, variables: dict[str, object]) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in variables:
            raise KeyError(f"prompt variable {{{{{key}}}}} was not provided")
        return str(variables[key])

    return re.sub(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", sub, template)


def versions() -> list[str]:
    def key(v: str) -> int:
        return int(v[1:]) if v[1:].isdigit() else 0

    return sorted((p.name for p in settings.prompts_dir.iterdir() if p.is_dir() and p.name.startswith("v")), key=key)
