"""Claude on Amazon Bedrock, by role.

Each role ("smart", "fast") has an ordered list of models. Transient failures are retried
with backoff; a model the account can't use (access denied, unknown id, refusal) is marked
dead for the rest of the process and the next model in the chain takes over.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

import neatlogs
from pydantic import BaseModel, ValidationError

from . import ledger, prompts
from .config import settings
from .obs import emit
from .resilience import Fatal, Retryable, chaos_hit, with_retries

M = TypeVar("M", bound=BaseModel)

_client = None
_dead: dict[str, str] = {}


def _get_client():
    global _client
    if _client is None:
        # Imported here so neatlogs.init() (obs.setup) has already patched the SDK.
        from anthropic import AnthropicBedrockMantle

        # Retries are ours (with_retries) so every one shows up in the event log and the trace.
        _client = AnthropicBedrockMantle(aws_region=settings.aws_region, max_retries=0, timeout=300.0)
    return _client


def _supports_effort(model: str) -> bool:
    return "haiku-4-5" not in model


def _call(model: str, system: str, user: str, effort: str | None, max_tokens: int) -> str:
    import anthropic

    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if effort and _supports_effort(model):
        kwargs["output_config"] = {"effort": effort}
    try:
        resp = _get_client().messages.create(**kwargs)
    except anthropic.RateLimitError as e:
        ra = e.response.headers.get("retry-after") if e.response is not None else None
        raise Retryable("429 rate limited", retry_after=float(ra) if ra and ra.isdigit() else None) from e
    except anthropic.APIStatusError as e:
        if e.status_code >= 500 or e.status_code in (408, 409):
            raise Retryable(f"HTTP {e.status_code}") from e
        raise Fatal(f"HTTP {e.status_code}: {str(e.message)[:200]}") from e
    except anthropic.APIConnectionError as e:
        raise Retryable(f"connection error: {type(e).__name__}") from e

    usage = resp.usage
    ledger.current().add_llm(model, usage.input_tokens or 0, usage.output_tokens or 0)
    if resp.stop_reason == "refusal":
        raise Fatal("model declined the request (refusal)")
    if resp.stop_reason == "max_tokens":
        emit("recover", f"{model} hit max_tokens={max_tokens}; output may be truncated")
    return "".join(b.text for b in resp.content if b.type == "text")


def complete(role: str, system: str, user: str, *, effort: str | None = None, max_tokens: int = 16000) -> tuple[str, str]:
    """Run one prompt on the first usable model for `role`. Returns (text, model_used)."""
    chain = settings.models_smart if role == "smart" else settings.models_fast
    last_error: Exception | None = None
    for i, model in enumerate(chain):
        if model in _dead:
            continue
        try:
            text = with_retries(lambda: _call(model, system, user, effort, max_tokens), what=f"llm {role}:{model.split('.')[-1]}")
        except Fatal as e:
            _dead[model] = str(e)
            last_error = e
            if i + 1 < len(chain):
                emit("recover", f"{model} unusable ({e}); falling back to {chain[i + 1]}", model=model)
                ledger.current().fallback_calls += 1
            continue
        except Retryable as e:
            last_error = e
            if i + 1 < len(chain):
                emit("recover", f"{model} kept failing ({e}); trying {chain[i + 1]}", model=model)
                ledger.current().fallback_calls += 1
            continue
        return text, model
    raise Fatal(f"no usable model for role '{role}': {last_error}")


def _extract_json(text: str):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    starts = [i for i in (t.find("{"), t.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON object in output")
    start = min(starts)
    end = max(t.rfind("}"), t.rfind("]"))
    return json.loads(t[start : end + 1])


def run_prompt(
    name: str,
    variables: dict[str, object],
    schema: type[M],
    *,
    role: str,
    effort: str | None = None,
    max_tokens: int = 16000,
    version: str | None = None,
) -> M:
    """Render prompts/<version>/<name>.md, call the model, and parse its JSON into `schema`.
    If the JSON is malformed, a cheap repair call fixes it rather than failing the run."""
    version = version or settings.prompts_version
    system_t, user_t = prompts.load(name, version)
    system, user = prompts.render(system_t, variables), prompts.render(user_t, variables)
    small_vars = {k: v for k, v in variables.items() if isinstance(v, (str, int, float)) and len(str(v)) < 200}

    with neatlogs.trace(
        f"prompt.{name}",
        kind="CHAIN",
        system_prompt_template=system_t,
        user_prompt_template=user_t,
        user_prompt_variables=small_vars,
        version=version,
    ):
        text, model = complete(role, system, user, effort=effort, max_tokens=max_tokens)
        if chaos_hit(f"llm.{name}", "malformed JSON from model"):
            text = text[: len(text) // 2]
        try:
            return schema.model_validate(_extract_json(text))
        except (ValueError, ValidationError) as e:
            emit("recover", f"{name}: invalid JSON from {model.split('.')[-1]} ({str(e)[:80]}); repairing", prompt=name)
            fixed, _ = complete(
                "fast",
                "You repair malformed JSON so it validates against a JSON Schema. "
                "Keep every value that is present; never invent content. Output only the JSON.",
                f"JSON Schema:\n{json.dumps(schema.model_json_schema())}\n\nValidation error:\n{str(e)[:1500]}\n\n"
                f"Broken output:\n{text}",
                max_tokens=max_tokens,
            )
            result = schema.model_validate(_extract_json(fixed))
            emit("recover", f"{name}: JSON repaired", prompt=name, recovered=True)
            return result
