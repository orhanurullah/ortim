# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Provider-agnostic wrapper around the Anthropic Messages API.

Both Anthropic and DeepSeek (via its Anthropic-compatible endpoint) use the
same SDK shape — `Anthropic(api_key=..., base_url=...)` — so the wrapper
only differs by which `ProviderConfig` it loads and which API key env it reads.

Agent code never sees the provider distinction; it calls `LLMClient.call()`
and gets back an `LLMResponse` carrying the provider/model that served the
request, which the caller logs into the audit trail for cost attribution.

Transient error handling: `call()` retries up to `MAX_RETRIES` times on
503/529/overloaded/connection errors with exponential backoff + jitter.
Override via `AI_FACTORY_LLM_MAX_RETRIES` env (default 3).
"""

from __future__ import annotations

import os
import random
import sys
import time
from dataclasses import dataclass

from anthropic import APIConnectionError, APIStatusError, Anthropic

from runtime.llm.providers import ProviderConfig, resolve_provider

# Retry budget. 3 retries = 4 total attempts with ~1s/2s/4s base delay.
MAX_RETRIES = int(os.getenv("AI_FACTORY_LLM_MAX_RETRIES", "3"))

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
        key = api_key or os.getenv(self.config.api_key_env)
        if not key:
            raise RuntimeError(
                f"{self.config.api_key_env} not set. "
                f"Configure .env or export the variable."
            )
        sdk_kwargs: dict[str, str] = {"api_key": key}
        if self.config.base_url:
            sdk_kwargs["base_url"] = self.config.base_url
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
