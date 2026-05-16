# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""LLM provider registry.

Each entry describes one LLM endpoint the pipeline can route to:
- Anthropic (native Messages API)
- DeepSeek (Anthropic-compatible endpoint at api.deepseek.com/anthropic)
- Ollama (local; OpenAI-compatible endpoint at localhost:11434/v1)

`api_kind` selects which on-the-wire schema the client speaks:
"anthropic" goes through the `anthropic` SDK; "openai" goes through a
plain httpx POST to /v1/chat/completions. Agent code is unaware — it
calls `LLMClient.call(system, user, ...)` and the wrapper picks the
right path.

Local providers (Ollama, LM Studio) set `api_key_env=None`; the client
skips the auth check for them. `OLLAMA_BASE_URL` lets an operator point
the local provider at a remote Ollama host.

Pricing is USD per 1M tokens. Local providers are priced 0.0 (real
cost is electricity + hardware amortization, not per-token). Verify
remote providers against their current pricing page before relying on
budget reports for spend decisions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key_env: str | None
    """Env var the client reads for the API key. `None` means the
    provider is local / unauthenticated and no key is required."""
    base_url: str | None
    default_model: str
    input_usd_per_m: float
    output_usd_per_m: float
    api_kind: str = "anthropic"
    """On-the-wire API schema. `"anthropic"` uses the anthropic SDK;
    `"openai"` uses a direct httpx POST to /chat/completions. Default
    keeps existing providers behaviorally identical."""


PROVIDERS: dict[str, ProviderConfig] = {
    "anthropic": ProviderConfig(
        name="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        base_url=None,
        default_model="claude-opus-4-7",
        input_usd_per_m=15.0,
        output_usd_per_m=75.0,
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com/anthropic",
        default_model="deepseek-chat",
        input_usd_per_m=0.27,
        output_usd_per_m=1.10,
    ),
    "ollama": ProviderConfig(
        name="ollama",
        api_key_env=None,
        base_url="http://localhost:11434/v1",
        default_model="qwen2.5-coder:7b",
        input_usd_per_m=0.0,
        output_usd_per_m=0.0,
        api_kind="openai",
    ),
}


class UnknownProvider(ValueError):
    pass


def resolve_provider(name: str | None = None) -> ProviderConfig:
    """Pick a provider config by explicit arg, env, or fall back to anthropic."""
    chosen = (name or os.getenv("LLM_PROVIDER", "anthropic")).strip().lower()
    if chosen not in PROVIDERS:
        valid = ", ".join(sorted(PROVIDERS))
        raise UnknownProvider(f"unknown LLM provider {chosen!r}; valid: {valid}")
    return PROVIDERS[chosen]


def pricing_for(provider: str, model: str) -> tuple[float, float]:
    """Return (input_usd_per_m, output_usd_per_m) for a (provider, model) pair.

    Defaults to the provider's primary pricing; per-model overrides can be
    layered on top later (e.g., `deepseek-reasoner` priced differently from
    `deepseek-chat`). For now both DeepSeek models share base pricing.
    """
    cfg = PROVIDERS.get(provider.lower())
    if cfg is None:
        return (PROVIDERS["anthropic"].input_usd_per_m, PROVIDERS["anthropic"].output_usd_per_m)
    return (cfg.input_usd_per_m, cfg.output_usd_per_m)
