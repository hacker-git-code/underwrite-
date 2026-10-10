"""Runtime settings, read once from the environment (and .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in _env(name, default).split(",") if x.strip()]


@dataclass
class Settings:
    # Claude on Amazon Bedrock (Messages API / "Mantle" endpoint).
    aws_region: str = field(default_factory=lambda: _env("AWS_REGION", "us-east-1"))
    # "smart" = planning, memo writing, coaching. "fast" = bulk extraction + verification.
    # Each role tries its models in order and skips any the account can't access.
    models_smart: list[str] = field(
        default_factory=lambda: _env_list(
            "UW_MODELS_SMART", "anthropic.claude-opus-5-5,anthropic.claude-sonnet-5,anthropic.claude-haiku-4-5"
        )
    )
    models_fast: list[str] = field(
        default_factory=lambda: _env_list("UW_MODELS_FAST", "anthropic.claude-haiku-5-5,anthropic.claude-haiku-4-5")
    )

    crustdata_api_key: str = field(default_factory=lambda: _env("CRUSTDATA_API_KEY"))
    neatlogs_api_key: str = field(default_factory=lambda: _env("NEATLOGS_API_KEY"))
    neatlogs_mcp_url: str = field(
        default_factory=lambda: _env("NEATLOGS_MCP_URL", "https://ingest.neatlogs.com/mcp")
    )

    prompts_version: str = field(default_factory=lambda: _env("UW_PROMPTS", "v1"))

    # Per-company research budget.
    max_searches: int = field(default_factory=lambda: int(_env("UW_MAX_SEARCHES", "8")))
    max_fetches: int = field(default_factory=lambda: int(_env("UW_MAX_FETCHES", "10")))
    max_rounds: int = field(default_factory=lambda: int(_env("UW_MAX_ROUNDS", "2")))
    page_chars: int = field(default_factory=lambda: int(_env("UW_PAGE_CHARS", "6000")))

    # Fault injection rate (0..1) for recovery demos. Injected faults are always labelled.
    chaos: float = field(default_factory=lambda: float(_env("UW_CHAOS", "0") or 0))

    cache_dir: Path = ROOT / ".cache"
    runs_dir: Path = ROOT / "runs"
    prompts_dir: Path = ROOT / "prompts"
    evals_dir: Path = ROOT / "evals"


settings = Settings()
