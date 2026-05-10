# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Provider-agnostic wrapper around the Anthropic Messages API.

Both Anthropic and DeepSeek (via its Anthropic-compatible endpoint) use the
same SDK shape — `Anthropic(api_key=..., base_url=...)` — so the wrapper
only differs by which `ProviderConfig` it loads and which API key env it reads.

Agent code never sees the provider distinction; it calls `LLMClient.call()`
and gets back an `LLMResponse` carrying the provider/model that served the
request, which the caller logs into the audit trail for cost attribution.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from anthropic import Anthropic

from runtime.llm.providers import ProviderConfig, resolve_provider


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str

    def audit_fields(self) -> dict[str, object]:
        """Standard audit log fields for this response — token usage + provider/model.

        Spread into `audit.log(...)` so every LLM call's row is attributable:

            audit.log("babel_extract_ok", project_id=pid, **resp.audit_fields())
        """
        return {
            "tokens": {"in": self.input_tokens, "out": self.output_tokens},
            "provider": self.provider,
            "model": self.model,
        }


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
        )
