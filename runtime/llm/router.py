# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Per-role LLM client factory.

Each agent role can run on a different provider/model. Routing precedence:

  1. Explicit args to `client_for(role, provider=..., model=...)`
  2. Role-specific env: `<ROLE>_PROVIDER`, `<ROLE>_MODEL`
     (e.g. `BABEL_PROVIDER`, `ARCHITECT_MODEL`)
  3. Global fallback: `LLM_PROVIDER`, `DEFAULT_MODEL`
  4. Provider's own `default_model`

This lets us run cheap/high-volume work (Babel, Analyst) on DeepSeek while
keeping critical decisions (Architect, SecurityReviewer) on Claude — without
agent code knowing or caring.
"""

from __future__ import annotations

import os

from runtime.llm.client import LLMClient

KNOWN_ROLES = frozenset({
    "babel",
    "analyst",
    "architect",
    "orchestrator",
    "worker",
    "reviewer",
    "security_reviewer",
    "test_reviewer",
    "perf_reviewer",
})


def _env_for(role: str, suffix: str) -> str | None:
    """Return value of `<ROLE>_<SUFFIX>` env var, if set and non-empty."""
    key = f"{role.upper()}_{suffix.upper()}"
    val = os.getenv(key)
    return val.strip() if val and val.strip() else None


def client_for(
    role: str,
    provider: str | None = None,
    model: str | None = None,
) -> LLMClient:
    """Build an LLMClient configured for `role`.

    `role` is informational for env lookup; unknown roles still resolve, they
    just won't have role-specific overrides applied.
    """
    role_norm = role.strip().lower()
    chosen_provider = provider or _env_for(role_norm, "PROVIDER")
    chosen_model = model or _env_for(role_norm, "MODEL")
    return LLMClient(provider=chosen_provider, model=chosen_model)
