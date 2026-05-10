# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Budget tracking — derives token usage and cost from the audit JSONL.

The audit log is the single source of truth. BudgetTracker is a derived view:
filter by project_id, sum tokens per (provider, model), apply that pair's
pricing. Reports also expose a per-provider breakdown so multi-LLM setups
(e.g., Babel/Analyst on DeepSeek, Architect on Claude) can be analyzed.

Backward compatibility: old audit rows that lack `provider`/`model` fields
default to Anthropic at the registry's stock price.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from runtime.llm.providers import PROVIDERS, pricing_for

DEFAULT_INPUT_USD_PER_M = PROVIDERS["anthropic"].input_usd_per_m
DEFAULT_OUTPUT_USD_PER_M = PROVIDERS["anthropic"].output_usd_per_m


@dataclass(frozen=True)
class ProviderBreakdown:
    provider: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    entry_count: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class BudgetReport:
    project_id: str | None
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    entry_count: int
    per_provider: dict[str, ProviderBreakdown] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class BudgetTracker:
    def __init__(
        self,
        audit_path: Path | None = None,
        input_usd_per_m: float | None = None,
        output_usd_per_m: float | None = None,
    ) -> None:
        """If `input_usd_per_m`/`output_usd_per_m` are set, they override the
        per-provider pricing for *every* provider — useful for tests with a
        synthetic flat rate. Without overrides, each row is priced by its own
        provider entry from `runtime.llm.providers.PROVIDERS`."""
        self.audit_path = audit_path or Path(
            os.getenv("AUDIT_LOG_PATH", "./runtime/audit/decisions.jsonl")
        )
        self.flat_input_usd_per_m = input_usd_per_m
        self.flat_output_usd_per_m = output_usd_per_m

    def _cost(self, in_tokens: int, out_tokens: int, provider: str) -> float:
        if (
            self.flat_input_usd_per_m is not None
            and self.flat_output_usd_per_m is not None
        ):
            in_per_m = self.flat_input_usd_per_m
            out_per_m = self.flat_output_usd_per_m
        else:
            in_per_m, out_per_m = pricing_for(provider, "")
        return round(
            (in_tokens / 1_000_000) * in_per_m
            + (out_tokens / 1_000_000) * out_per_m,
            6,
        )

    def report(
        self,
        project_id: str | None = None,
        tenant_id: str | None = None,
    ) -> BudgetReport:
        if not self.audit_path.exists():
            return BudgetReport(project_id, 0, 0, 0.0, 0)

        per_prov_in: dict[str, int] = defaultdict(int)
        per_prov_out: dict[str, int] = defaultdict(int)
        per_prov_count: dict[str, int] = defaultdict(int)

        with self.audit_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if tenant_id is not None and entry.get("tenant_id", "default") != tenant_id:
                    continue

                if project_id and entry.get("project_id") != project_id:
                    continue

                tokens = entry.get("tokens")
                if not isinstance(tokens, dict):
                    continue
                in_tokens = int(tokens.get("in", 0))
                out_tokens = int(tokens.get("out", 0))
                if in_tokens == 0 and out_tokens == 0:
                    continue

                provider = str(entry.get("provider") or "anthropic").lower()
                per_prov_in[provider] += in_tokens
                per_prov_out[provider] += out_tokens
                per_prov_count[provider] += 1

        per_provider: dict[str, ProviderBreakdown] = {}
        total_in = 0
        total_out = 0
        total_cost = 0.0
        total_count = 0
        for provider in per_prov_in:
            in_t = per_prov_in[provider]
            out_t = per_prov_out[provider]
            cost = self._cost(in_t, out_t, provider)
            per_provider[provider] = ProviderBreakdown(
                provider=provider,
                input_tokens=in_t,
                output_tokens=out_t,
                estimated_cost_usd=cost,
                entry_count=per_prov_count[provider],
            )
            total_in += in_t
            total_out += out_t
            total_cost += cost
            total_count += per_prov_count[provider]

        return BudgetReport(
            project_id=project_id,
            input_tokens=total_in,
            output_tokens=total_out,
            estimated_cost_usd=round(total_cost, 6),
            entry_count=total_count,
            per_provider=per_provider,
        )

    def is_under_cap(self, project_id: str, total_token_cap: int) -> bool:
        report = self.report(project_id)
        return report.total_tokens < total_token_cap
