# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""ScopeManifest — the single source of truth for MVP scope decisions.

After PRD draft and before G1 approval, the user passes through
MVP_SCOPE_LOCKING. Each feature from `StructuredIntent.must_have_features`
+ `nice_to_have_features` becomes a `ScopedFeature` with explicit
`phase` and `priority`. Downstream layers (Architect §7 two-tier module
table, Orchestrator phase ordering, `ortim run-all --phase N`) read this
artifact instead of inferring scope from the flat feature list.

The old gap (Item §4 of 16-05-2026_app-state.md): `must_have_features`
was a flat list with no MVP signal — Architect implicitly picked
"smallest viable", but the user could not say "auth MVP, social login
Phase 2". ScopeManifest closes that gap.

Priority is intentionally binary (`must` / `later`) for v1; MoSCoW
breadth deferred to Faz 2 of the Q2 roadmap.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Priority = Literal["must", "later"]


class ScopedFeature(BaseModel):
    """A single feature with its scope decision.

    `description` mirrors the wording from `StructuredIntent.*_features`
    when the feature was seeded from intent; manual additions during
    `ortim scope` use whatever the user typed. Downstream prompts read
    `description` verbatim — keep the text user-facing.
    """

    description: str
    phase: int = 1
    """1 = MVP. 2+ = later phases. Orchestrator orders execution by phase."""

    priority: Priority = "must"
    """`must` features go into Phase 1 by default. `later` features are
    parked in Phase 2+. Binary on purpose (see module docstring)."""

    rationale: str = ""
    """Optional user note: why this feature is in this phase. Carried
    to RFC §7 + audit log so the decision is reviewable later."""

    source: Literal["intent", "manual"] = "intent"
    """Provenance — `intent` was seeded from StructuredIntent, `manual`
    was added during `ortim scope`. Used by the CLI to highlight new
    features the user might have missed in earlier dialog states."""

    @field_validator("phase")
    @classmethod
    def _phase_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"phase must be >= 1 (got {v})")
        return v

    @field_validator("description")
    @classmethod
    def _description_nonblank(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("description must not be blank")
        return s


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScopeManifest(BaseModel):
    """Project-level scope artifact (`scope.json`).

    Created during MVP_SCOPE_LOCKING transition; consumed by Architect
    Call 2 (RFC §7 two-tier module table), Orchestrator (phase tagging
    per TaskSpec), and `ortim run-all --phase N` (execution filter).
    """

    version: int = 1
    project_id: str
    features: list[ScopedFeature] = Field(default_factory=list)
    locked_at: str | None = None
    """ISO timestamp set when the user advances MVP_SCOPE_LOCKING →
    PRD_AWAITING_APPROVAL. None while still being edited."""

    def phase_1_features(self) -> list[ScopedFeature]:
        return [f for f in self.features if f.phase == 1]

    def deferred_features(self) -> list[ScopedFeature]:
        return [f for f in self.features if f.phase >= 2]

    def max_phase(self) -> int:
        return max((f.phase for f in self.features), default=1)

    def lock(self) -> None:
        """Stamp `locked_at` immutably. Idempotent for the same instant."""
        if self.locked_at is None:
            self.locked_at = _utcnow()

    def to_prompt_block(self) -> str:
        """Compact markdown for Architect / Orchestrator prompts.

        Lists Phase 1 features inline and groups Phase 2+ as a deferred
        block. Keeps the prompt cost predictable: ~50 tokens per feature.
        """
        if not self.features:
            return "_(no features scoped)_"
        lines: list[str] = ["**Phase 1 (MVP) features:**"]
        for f in self.phase_1_features():
            lines.append(f"- {f.description}")
        deferred = self.deferred_features()
        if deferred:
            lines.append("")
            lines.append("**Deferred (Phase 2+):**")
            for f in deferred:
                lines.append(f"- [P{f.phase}] {f.description}")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Standalone artifact (`scope.md`) the user reads via
        `ortim show <id> --artifact scope`."""
        lines: list[str] = [
            "# Scope Manifest",
            "",
            f"- **Project:** `{self.project_id}`",
            f"- **Locked at:** {self.locked_at or '_(not yet locked)_'}",
            f"- **Max phase:** {self.max_phase()}",
            "",
            "## Features",
            "",
            "| Phase | Priority | Source | Description | Rationale |",
            "|---|---|---|---|---|",
        ]
        for f in self.features:
            rationale = f.rationale.strip() or "—"
            lines.append(
                f"| {f.phase} | {f.priority} | {f.source} | {f.description} | {rationale} |"
            )
        return "\n".join(lines) + "\n"


def suggest_initial_scope(
    project_id: str,
    must_have_features: list[str],
    nice_to_have_features: list[str],
) -> ScopeManifest:
    """Seed a ScopeManifest from a StructuredIntent's feature lists.

    Default mapping (the auto-suggestion the user can override in
    `ortim scope`):
      - must_have_features  → phase=1, priority="must"
      - nice_to_have_features → phase=2, priority="later"

    The user is expected to walk the list and either accept the defaults
    or reassign. `locked_at` stays None until the CLI explicitly locks.
    """
    features: list[ScopedFeature] = []
    for desc in must_have_features:
        features.append(
            ScopedFeature(
                description=desc,
                phase=1,
                priority="must",
                source="intent",
            )
        )
    for desc in nice_to_have_features:
        features.append(
            ScopedFeature(
                description=desc,
                phase=2,
                priority="later",
                source="intent",
            )
        )
    return ScopeManifest(project_id=project_id, features=features)


def scope_path(workspace: Path) -> Path:
    return workspace / "scope.json"


def load_scope(workspace: Path) -> ScopeManifest:
    """Load `scope.json` from a workspace. Raises FileNotFoundError if
    the project has not yet passed MVP_SCOPE_LOCKING."""
    return ScopeManifest.model_validate_json(
        scope_path(workspace).read_text(encoding="utf-8")
    )


def save_scope(workspace: Path, manifest: ScopeManifest) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    scope_path(workspace).write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
