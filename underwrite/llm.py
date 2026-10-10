"""LLM access by role, across providers.

A model is written "provider:model", e.g. "gemini:gemini-2.5-flash" or "groq:openai/gpt-oss-120b".
Each role ("smart", "fast") has an ordered chain of models. Transient failures are retried with
backoff; a model that can't serve us (no key, unknown id, daily quota gone, request too large,
refusal) is marked dead for the rest of the process and the next model in the chain takes over.

Gemini, Groq, Cerebras and OpenRouter speak the OpenAI-compatible API (traced by neatlogs'
`openai` instrumentation). Claude on Amazon Bedrock is supported too ("bedrock:anthropic.claude-...").
"""

from __future__ import annotations

import json
import os
import re
from typing import TypeVar

import neatlogs
from pydantic import BaseModel, ValidationError

from . import ledger, prompts
from .config import settings
from .obs import emit
from .resilience import Fatal, RateLimiter, Retryable, chaos_hit, with_retries

M = TypeVar("M", bound=BaseModel)

# OpenAI-compatible providers: base URL, key env var, and a client-side requests-per-minute cap
# matching their free tiers so we wait politely instead of hammering into 429s.
PROVIDERS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", 10),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", 30),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", 30),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", 20),
}

_clients: dict[str, object] = {}
_limiters: dict[str, RateLimiter] = {}
_dead: dict[str, str] = {}


def split_model(spec: str) -> tuple[str, str]:
    if ":" in spec and spec.split(":", 1)[0] in (*PROVIDERS, "bedrock"):
        return tuple(spec.split(":", 1))  # type: ignore[return-value]
    if spec.startswith("anthropic."):
        return "bedrock", spec
    raise ValueError(f"model '{spec}' needs a provider prefix, e.g. gemini:{spec}")


def provider_ready(provider: str) -> bool:
    if provider == "bedrock":
        return any(os.environ.get(k) for k in ("AWS_BEARER_TOKEN_BEDROCK", "AWS_ACCESS_KEY_ID", "AWS_PROFILE"))
    return bool(os.environ.get(PROVIDERS[provider][1]))


def _client(provider: str):
    if provider not in _clients:
        # Imported lazily so neatlogs.init() (obs.setup) has already instrumented the SDKs.
        # max_retries=0: retries are ours, so each one shows up in the event log and the trace.
        if provider == "bedrock":
            from anthropic import AnthropicBedrockMantle

            _clients[provider] = AnthropicBedrockMantle(aws_region=settings.aws_region, max_retries=0, timeout=300.0)
        else:
            from openai import OpenAI

            base_url, key_env, rpm = PROVIDERS[provider]
            _clients[provider] = OpenAI(base_url=base_url, api_key=os.environ[key_env], max_retries=0, timeout=300.0)
            _limiters[provider] = RateLimiter(rate=rpm, per=60.0)
    return _clients[provider]


def _daily_quota(msg: str) -> bool:
    m = msg.lower()
    return any(s in m for s in ("per day", "perday", "daily", "requests per day", "quota exceeded", "tokens per day"))


def _call_openai(provider: str, model: str, system: str, user: str, effort: str | None, max_tokens: int) -> str:
    import openai

    client = _client(provider)
    _limiters[provider].acquire()
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if effort and (model.startswith("gemini-2.5") or model.startswith("gemini-3") or "gpt-oss" in model):
        kwargs["reasoning_effort"] = effort
    try:
        resp = client.chat.completions.create(**kwargs)
    except openai.RateLimitError as e:
        if _daily_quota(str(e)):
            raise Fatal(f"daily quota exhausted: {str(e)[:160]}") from e
        ra = e.response.headers.get("retry-after") if e.response is not None else None
        raise Retryable("429 rate limited", retry_after=float(ra) if ra and ra.replace(".", "").isdigit() else None) from e
    except openai.APIStatusError as e:
        if e.status_code >= 500 or e.status_code in (408, 409):
            raise Retryable(f"HTTP {e.status_code}") from e
        if e.status_code == 400 and "json" in str(e).lower() and "valid" in str(e).lower():
            raise Retryable("provider rejected its own malformed JSON") from e
        raise Fatal(f"HTTP {e.status_code}: {str(e)[:200]}") from e
    except openai.APIConnectionError as e:
        raise Retryable(f"connection error: {type(e).__name__}") from e

    if resp.usage:
        ledger.current().add_llm(f"{provider}:{model}", resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0)
    choice = resp.choices[0]
    if choice.finish_reason == "length":
        emit("recover", f"{model} hit max_tokens={max_tokens}; output may be truncated")
    return choice.message.content or ""


def _call_bedrock(model: str, system: str, user: str, effort: str | None, max_tokens: int) -> str:
    import anthropic

    kwargs: dict = {"model": model, "max_tokens": max_tokens, "system": system,
                    "messages": [{"role": "user", "content": user}]}
    if effort and "haiku-4-5" not in model:
        kwargs["output_config"] = {"effort": effort}
    try:
        resp = _client("bedrock").messages.create(**kwargs)
    except anthropic.RateLimitError as e:
        ra = e.response.headers.get("retry-after") if e.response is not None else None
        raise Retryable("429 rate limited", retry_after=float(ra) if ra and ra.isdigit() else None) from e
    except anthropic.APIStatusError as e:
        if e.status_code >= 500 or e.status_code in (408, 409):
            raise Retryable(f"HTTP {e.status_code}") from e
        raise Fatal(f"HTTP {e.status_code}: {str(e.message)[:200]}") from e
    except anthropic.APIConnectionError as e:
        raise Retryable(f"connection error: {type(e).__name__}") from e

    ledger.current().add_llm(f"bedrock:{model}", resp.usage.input_tokens or 0, resp.usage.output_tokens or 0)
    if resp.stop_reason == "refusal":
        raise Fatal("model declined the request (refusal)")
    if resp.stop_reason == "max_tokens":
        emit("recover", f"{model} hit max_tokens={max_tokens}; output may be truncated")
    return "".join(b.text for b in resp.content if b.type == "text")


def call(spec: str, system: str, user: str, effort: str | None = None, max_tokens: int = 16000) -> str:
    provider, model = split_model(spec)
    if not provider_ready(provider):
        raise Fatal(f"no API key for {provider}")
    if provider == "bedrock":
        return _call_bedrock(model, system, user, effort, max_tokens)
    return _call_openai(provider, model, system, user, effort, max_tokens)


def complete(role: str, system: str, user: str, *, effort: str | None = None, max_tokens: int = 16000) -> tuple[str, str]:
    """Run one prompt on the first usable model for `role`. Returns (text, model_used)."""
    chain = [m for m in (settings.models_smart if role == "smart" else settings.models_fast)
             if provider_ready(split_model(m)[0])]
    last_error: Exception | None = None
    for i, spec in enumerate(chain):
        if spec in _dead:
            continue
        nxt = next((m for m in chain[i + 1 :] if m not in _dead), None)
        try:
            text = with_retries(lambda: call(spec, system, user, effort, max_tokens), what=f"llm {role}:{spec}")
        except (Fatal, Retryable) as e:
            if isinstance(e, Fatal):
                _dead[spec] = str(e)
            last_error = e
            if nxt:
                emit("recover", f"{spec} failed ({str(e)[:120]}); falling back to {nxt}", model=spec)
                ledger.current().fallback_calls += 1
            continue
        return text, spec
    raise Fatal(f"no usable model for role '{role}' (set GEMINI_API_KEY / GROQ_API_KEY in .env): {last_error}")


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
            emit("recover", f"{name}: invalid JSON from {model} ({str(e)[:80]}); repairing", prompt=name)
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
