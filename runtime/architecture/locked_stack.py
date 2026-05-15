# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""LockedStack — the single source of truth for a project's tech stack.

After M2 STACK_DIALOG lock, every downstream layer (bootstrap, Architect
Call 2, Documenter) reads this artifact instead of inferring stack from
deterministic matrices (`_LANG_STACK_BY_TIER_APP`, `_infer_test_cmd_from_rfc`).

Old `tespit.md` items 2 + 17 + 18 stemmed from three layers having
independent opinions about the stack; LockedStack collapses them to one.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LockedStack(BaseModel):
    """Structured stack decision locked by the user in STACK_DIALOG.

    `tier` and `app_class` are typed as plain strings (rather than the
    `Tier` / `AppClass` enums) so an older `stack.json` from a project
    using a tier value we have since removed still loads — the consumer
    can validate against the live enums.
    """

    version: int = 1
    tier: str
    app_class: str

    language: str
    """e.g. "TypeScript", "Python", "Dart", "Go"."""

    primary_framework: str
    """e.g. "Node + Hono", "FastAPI", "Flutter", "Cobra"."""

    package_manager: str
    """e.g. "npm", "pip", "pub", "go modules"."""

    test_cmd: str
    """Command the test runner invokes (e.g. `npx vitest run`,
    `flutter test`, `pytest`, `go test ./...`)."""

    run_cmd: str
    """How to start the application locally (e.g. `npm start`,
    `flutter run`, `python -m app`, `./bin/app`). README install/run
    sections derive from this."""

    key_libraries: list[str] = Field(default_factory=list)
    """Notable libraries the user explicitly named or the agent
    proposed: `["commander", "uuid"]`, `["riverpod", "dio"]`,
    `["typer", "pydantic"]`. Order is significance."""

    deploy_target: str = ""
    """Deployment hint: `"docker"`, `"vercel"`, `"app-store"`, `"none"`.
    Empty string is acceptable (T0 single-binary CLI doesn't need one)."""

    rationale: str = ""
    """One paragraph: why this stack for this intent. Surfaced to user
    on `ortim show <id> --artifact stack`."""

    def to_prompt_block(self) -> str:
        """Render the locked stack as a prompt-ready markdown block for
        Architect Call 2, Documenter, etc. Keep it compact (~300 chars)."""
        libs = ", ".join(self.key_libraries) if self.key_libraries else "(none specified)"
        deploy = self.deploy_target or "(unspecified)"
        return (
            f"**Tier:** {self.tier} ({self.app_class})\n"
            f"**Language:** {self.language}\n"
            f"**Primary framework:** {self.primary_framework}\n"
            f"**Package manager:** {self.package_manager}\n"
            f"**Test command:** `{self.test_cmd}`\n"
            f"**Run command:** `{self.run_cmd}`\n"
            f"**Key libraries:** {libs}\n"
            f"**Deploy target:** {deploy}\n"
        )

    def to_markdown(self) -> str:
        """Render the locked stack as a standalone artifact (`stack.md`)
        the user reads via `ortim show <id> --artifact stack`."""
        libs = "\n".join(f"- {lib}" for lib in self.key_libraries) or "_(none specified)_"
        deploy = self.deploy_target or "_(unspecified)_"
        rationale = self.rationale.strip() or "_(no rationale recorded)_"
        return (
            f"# Locked Stack\n\n"
            f"- **Tier:** `{self.tier}` ({self.app_class})\n"
            f"- **Language:** {self.language}\n"
            f"- **Primary framework:** {self.primary_framework}\n"
            f"- **Package manager:** {self.package_manager}\n"
            f"- **Test command:** `{self.test_cmd}`\n"
            f"- **Run command:** `{self.run_cmd}`\n"
            f"- **Deploy target:** {deploy}\n\n"
            f"## Key libraries\n\n"
            f"{libs}\n\n"
            f"## Rationale\n\n"
            f"{rationale}\n"
        )
