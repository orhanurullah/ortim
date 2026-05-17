# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Provider-agnostic wrapper around two on-the-wire LLM schemas.

`api_kind="anthropic"` providers (Anthropic native + DeepSeek's
Anthropic-compatible endpoint) go through the `anthropic` Python SDK
— only `base_url` differs. `api_kind="openai"` providers (Ollama,
LM Studio, any OpenAI-compatible local server) go through a plain
httpx POST to `/v1/chat/completions`. Both paths return an
`LLMResponse` with the same shape.

Agent code never sees the provider distinction; it calls
`LLMClient.call()` and gets back an `LLMResponse` carrying the
provider/model that served the request, which the caller logs into
the audit trail for cost attribution.

Local-provider quirks:
  - `api_key_env=None` providers skip the auth check.
  - `OLLAMA_BASE_URL` env overrides the default localhost URL — useful
    when Ollama runs on another host or behind a reverse proxy.

Transient error handling: `call()` retries up to `MAX_RETRIES` times
on 503/529/connection/timeout errors with exponential backoff + jitter.
Override via `ORTIM_LLM_MAX_RETRIES` env (default 3). Both
`api_kind`s share the same retry loop.
"""

from __future__ import annotations

import os
import random
import sys
import time
from dataclasses import dataclass

import httpx
from anthropic import APIConnectionError, APIStatusError, Anthropic

from ortim.env import env_get
from ortim.llm.providers import ProviderConfig, resolve_provider

# Retry budget. 3 retries = 4 total attempts with ~1s/2s/4s base delay.
MAX_RETRIES = int(env_get("ORTIM_LLM_MAX_RETRIES", "3") or "3")

# HTTP status codes that are safe (and advisable) to retry.
_RETRYABLE_STATUS_CODES = frozenset({429, 503, 529})


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str
    retries: int = 0

    def audit_fields(self) -> dict[str, object]:
        """Standard audit log fields for this response — token usage + provider/model.

        Spread into `audit.log(...)` so every LLM call's row is attributable:

            audit.log("babel_extract_ok", project_id=pid, **resp.audit_fields())
        """
        fields: dict[str, object] = {
            "tokens": {"in": self.input_tokens, "out": self.output_tokens},
            "provider": self.provider,
            "model": self.model,
        }
        if self.retries:
            fields["retries"] = self.retries
        return fields


def _is_retryable(exc: Exception) -> bool:
    """Return True if the exception represents a transient LLM error."""
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in _RETRYABLE_STATUS_CODES
    # httpx transient shapes (used by the OpenAI-kind path for local LLMs).
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS_CODES
    # DeepSeek sometimes returns "Service is too busy" inside a 200-shaped
    # error; the anthropic SDK raises a generic APIError for those.
    msg = str(exc).lower()
    if "overloaded" in msg or "too busy" in msg or "rate limit" in msg:
        return True
    return False


class LLMClient:
    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.config: ProviderConfig = resolve_provider(provider)

        # Explicit api_key arg always wins, regardless of provider.
        # When the provider declares an api_key_env, fall back to it and
        # raise if neither source produced a key. Local providers
        # (api_key_env=None) accept an optional key for openai-compatible
        # servers that require auth (LM Studio with auth enabled etc.)
        # but don't require one.
        key: str | None = api_key
        if self.config.api_key_env is not None:
            if not key:
                key = os.getenv(self.config.api_key_env)
            if not key:
                raise RuntimeError(
                    f"{self.config.api_key_env} not set. "
                    f"Configure .env or export the variable."
                )
        self.api_key: str | None = key

        # Allow operator override of the base URL for local providers.
        # OLLAMA_BASE_URL is the most common case (Ollama on a remote
        # host or behind a reverse proxy); other openai-kind providers
        # can use OPENAI_BASE_URL for a generic override.
        base_url = self.config.base_url
        if self.config.name == "ollama":
            base_url = os.getenv("OLLAMA_BASE_URL", base_url)
        elif self.config.api_kind == "openai":
            base_url = os.getenv("OPENAI_BASE_URL", base_url)
        self.base_url: str | None = base_url

        # Build the anthropic SDK client only when we'll actually use it.
        self.client: Anthropic | None = None
        if self.config.api_kind == "anthropic":
            sdk_kwargs: dict[str, str] = {"api_key": key or ""}
            if base_url:
                sdk_kwargs["base_url"] = base_url
            self.client = Anthropic(**sdk_kwargs)

        self.model = (
            model
            or os.getenv("DEFAULT_MODEL")
            or self.config.default_model
        )

    @property
    def provider(self) -> str:
        return self.config.name

    def call(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        last_exc: Exception | None = None
        retries_used = 0

        for attempt in range(1 + MAX_RETRIES):
            try:
                if self.config.api_kind == "openai":
                    return self._call_openai(
                        system, user, temperature, max_tokens, retries_used
                    )
                return self._call_anthropic(
                    system, user, temperature, max_tokens, retries_used
                )
            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc) or attempt >= MAX_RETRIES:
                    raise
                retries_used = attempt + 1
                # Exponential backoff: 1s, 2s, 4s + up to 1s jitter.
                delay = (2 ** attempt) + random.uniform(0, 1.0)
                print(
                    f"[ortim] LLM transient error ({type(exc).__name__}: "
                    f"{exc}); retry {retries_used}/{MAX_RETRIES} "
                    f"in {delay:.1f}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)

        # Should never reach here, but satisfy type checker.
        raise last_exc  # type: ignore[misc]

    def _call_anthropic(
        self,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        retries_used: int,
    ) -> LLMResponse:
        assert self.client is not None, "anthropic SDK client not initialized"
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text_parts = [
            block.text
            for block in message.content
            if getattr(block, "type", None) == "text"
        ]
        return LLMResponse(
            text="".join(text_parts),
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            model=self.model,
            provider=self.config.name,
            retries=retries_used,
        )

    def _call_openai(
        self,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        retries_used: int,
    ) -> LLMResponse:
        """POST /v1/chat/completions against an OpenAI-compatible endpoint.

        Used by Ollama and LM Studio (any provider with
        `api_kind='openai'`). Token usage is read from the OpenAI-shape
        `usage` block; some Ollama versions omit it, in which case the
        counts default to 0 so audit downstream still works.
        """
        if not self.base_url:
            raise RuntimeError(
                f"provider '{self.config.name}' is openai-kind but has no "
                f"base_url configured"
            )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Default 5-minute timeout — local quantized models on commodity
        # hardware can take 30-90s for a 2K-token completion; remote
        # Ollama via slow LAN even more.
        response = httpx.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
            timeout=httpx.Timeout(300.0),
        )
        response.raise_for_status()
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"unexpected response shape from {self.config.name} at "
                f"{self.base_url}: {data!r}"
            ) from exc
        usage = data.get("usage") or {}
        return LLMResponse(
            text=content,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            model=self.model,
            provider=self.config.name,
            retries=retries_used,
        )
