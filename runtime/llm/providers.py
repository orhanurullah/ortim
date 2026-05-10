# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""LLM provider registry.

Each entry describes a provider that speaks the Anthropic Messages API:
- Anthropic (native)
- DeepSeek (via the Anthropic-compatible endpoint at api.deepseek.com/anthropic)

The `anthropic` Python SDK is used for both — only `base_url` differs.
This means agent code calls `LLMClient.call(system, user, ...)` once and the
provider is decided at construction time via env vars or explicit args.

Pricing is in USD per 1M tokens; verify against each provider's current
pricing page before relying on budget reports for spend decisions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key_env: str
    base_url: str | None
    default_model: str
    input_usd_per_m: float
    output_usd_per_m: float


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
