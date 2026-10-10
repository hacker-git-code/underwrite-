"""Tiny on-disk JSON cache. Saves Crustdata credits and makes eval reruns use identical evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .config import settings


def _path(namespace: str, key: Any):
    digest = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:24]
    return settings.cache_dir / namespace / f"{digest}.json"


def get(namespace: str, key: Any) -> Any | None:
    p = _path(namespace, key)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def put(namespace: str, key: Any, value: Any) -> None:
    p = _path(namespace, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
