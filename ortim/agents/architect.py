# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Architect agent — PRD → GoldenPathInputs (LLM) → tier (deterministic) → RFC (LLM).

The split is intentional: an LLM cannot pick the tier, only describe what
the PRD asks for. The scorer (deterministic, rule-based) picks the tier.
This prevents "sounds enterprise so let's microservice" failure modes.
"""

from __future__ import annotations

import re

from ortim.architecture import (
    GoldenPathInputs,
    LockedStack,
    TierScore,
    select_tier,
    stack_constraint,
)
from ortim.audit import AuditLogger
from ortim.babel.intent import _strip_code_fences
from ortim.codebase import CodebaseSummary
from ortim.llm import LLMClient
from ortim.memory import MemoryLoader
from ortim.scope import ScopeManifest

_CODEBASE_PROMPT_BUDGET_BYTES = 2000

# Item 40 — Architect must not introduce libraries that the user did not
# negotiate during STACK_DIALOG. Proof-point E2E showed the Architect
# silently adding `zustand` to RFC §4 even though the locked stack listed
# only [sql.js, zod]. Phantom libraries cascade: Worker imports them, deps
# aren't installed (item 41 separately addresses install gaps), Reviewer
# correctly flags an L1 violation, retry loop burns budget. The fix is two
# layers — stronger prompt + deterministic post-draft validator with a
# bounded retry loop, matching the reviewer length-validator pattern from
# item 21.
_RFC_DRAFT_MAX_RETRIES = 3


def _parse_rfc_key_libraries(rfc_text: str) -> list[str] | None:
    """Extract the comma-separated `**Key libraries:**` list from RFC §4
    Tech Stack.

    Returns the parsed list of library names (parenthetical comments
    stripped), or `None` when §4 or the line is missing. `None` means "no
    claim made" — caller should not flag drift in that case.
    """
    tech_stack = re.search(r"##\s*\d*\.?\s*Tech Stack\b", rfc_text, re.IGNORECASE)
    if not tech_stack:
        return None
    section_start = tech_stack.end()
    next_section = re.search(r"\n##\s", rfc_text[section_start:])
    section_end = section_start + (
        next_section.start() if next_section else len(rfc_text) - section_start
    )
    section = rfc_text[section_start:section_end]

    libs_match = re.search(
        r"\*\*Key libraries:\*\*\s*(.+)", section, re.IGNORECASE
    )
    if not libs_match:
        return None

    libs: list[str] = []
    for part in libs_match.group(1).split(","):
        cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", part.strip()).strip()
        # Strip trailing markdown emphasis/punctuation that sometimes leaks
        # in (e.g. `zod*` or `zod;`).
        cleaned = cleaned.rstrip("*;.,")
        if cleaned and cleaned.lower() != "(none specified)":
            libs.append(cleaned)
    return libs


def _find_phantom_libraries(
    rfc_text: str, locked_stack: "LockedStack"
) -> list[str]:
    """Return libraries listed in RFC §4 but NOT in locked_stack.key_libraries.

    Comparison is case-insensitive and whitespace-normalized. Empty list
    means RFC §4 is a subset of the locked stack (no drift).
    """
    extracted = _parse_rfc_key_libraries(rfc_text)
    if extracted is None:
        # Couldn't parse — don't flag drift on a parsing edge case.
        return []
    locked_set = {lib.strip().lower() for lib in locked_stack.key_libraries}
    return [lib for lib in extracted if lib.strip().lower() not in locked_set]


class ArchitectAgent:
    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryLoader,
        audit: AuditLogger,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.audit = audit

    def extract_inputs(
        self,
        prd_markdown: str,
        project_id: str,
        codebase: CodebaseSummary | None = None,
    ) -> GoldenPathInputs:
        system_prompt = self.memory.load_agent_prompt("architect")
        codebase_block = ""
        if codebase is not None:
            codebase_block = (
                "## Existing codebase summary\n\n"
                + codebase.to_prompt_text(_CODEBASE_PROMPT_BUDGET_BYTES)
                + "\n\nTreat the codebase as ground truth for module structure and "
                "tech stack. Set app_class from the detected hint above.\n\n"
            )
        user_prompt = (
            f"{codebase_block}"
            "PRD:\n\n```\n" + prd_markdown + "\n```\n\n"
            "Perform Call 1 only: extract GoldenPathInputs JSON. "
            "Output ONLY the JSON object."
        )
        response = self.llm.call(
            system=system_prompt,
            user=user_prompt,
            temperature=0.0,
            max_tokens=1500,
        )
        cleaned = _strip_code_fences(response.text)
        inputs = GoldenPathInputs.model_validate_json(cleaned)
        self.audit.log(
            "architect_extract_inputs",
            project_id=project_id,
            inputs=inputs.model_dump(),
            **response.audit_fields(),
        )
        return inputs

    def draft_rfc(
        self,
        prd_markdown: str,
        tier_score: TierScore,
        project_name: str,
        project_id: str,
        app_class: str = "web",
        codebase: CodebaseSummary | None = None,
        locked_stack: LockedStack | None = None,
        scope: ScopeManifest | None = None,
        user_stack_hints: list[str] | None = None,
    ) -> str:
        system_prompt = self.memory.load_agent_prompt("architect")
        principles = self.memory.load_l1_principles()
        template = self.memory.load_template("RFC")

        tier_brief = self._tier_brief(tier_score)
        tier_doc = self.memory.load_tier_doc(tier_score.tier.value)
        tier_doc_block = (
            f"\n\n## Selected Tier Reference Doc\n\n{tier_doc}"
            if tier_doc
            else ""
        )

        # M2: when a LockedStack exists (post STACK_DIALOG lock), it is
        # the SINGLE source of truth — verbatim into the prompt as a hard
        # constraint. Heuristic _LANG_STACK_BY_TIER_APP is bypassed.
        # Closes items 17 + 18 structurally for the dialog flow.
        if locked_stack is not None:
            allowed = ", ".join(locked_stack.key_libraries) or "(none — leave empty)"
            stack_block = (
                "\n\n## Locked Stack (HARD — copy verbatim into §4 Tech Stack)\n\n"
                + locked_stack.to_prompt_block()
                + "\nDo NOT deviate from these picks. They were negotiated "
                "with the user during STACK_DIALOG. If you believe a pick is "
                "wrong, raise the concern in §1 (Architectural Trade-offs) "
                "as advisory only — never silently switch.\n\n"
                "**HARD RULE FOR §4 'Key libraries' LINE.** The comma-separated "
                f"list under `- **Key libraries:**` in §4 MUST be EXACTLY: "
                f"`{allowed}`. Quote them verbatim. Do NOT add libraries "
                "(e.g. state-management libs like zustand or redux, HTTP clients "
                "like axios, utility libs like lodash) — those choices belong to "
                "STACK_DIALOG, not the RFC. Drop nothing; add nothing; reorder "
                "nothing. If you genuinely need an additional library to make "
                "the architecture work, raise it as a `**[NEEDS-INPUT]**` "
                "question in §1, do NOT embed it in §4.\n"
            )
        else:
            # Faz 1.2 B-2 fix — when locked_stack is None but Babel
            # extracted explicit user_stack_hints, those names win over
            # the tier-default constraint. Proof-point bf761fff02b0 showed
            # T2/BaaS tier silently substituted Supabase+PostgreSQL even
            # when the user wrote "Python + FastAPI + SQLite". The hint
            # block sits ABOVE the tier-constraint block so the LLM sees
            # user names first.
            hint_block = ""
            if user_stack_hints:
                hint_block = (
                    "\n\n## User-Named Stack (HARD — quote verbatim in §4)\n\n"
                    "The user explicitly named these technologies in the brief:\n"
                    + "\n".join(f"- {h}" for h in user_stack_hints)
                    + "\n\n**HARD RULE.** §4 Tech Stack MUST use these exact names. "
                    "Use tier defaults ONLY to fill gaps the user did not name "
                    "(e.g. user said 'Python' but no framework — fill from tier "
                    "defaults). Never SUBSTITUTE a user-named tool with a tier "
                    "default (e.g. user said 'SQLite' — do NOT pick PostgreSQL, "
                    "Supabase, or any other database). If a user-named tool "
                    "appears wrong for the selected tier, surface the conflict "
                    "as `**[NEEDS-INPUT]**` in §1, do NOT silently substitute.\n"
                )

            # Item 17 fix: thread the (tier, app_class) language/framework
            # constraint into the prompt so Architect Call 2 cannot pick a
            # stack inconsistent with the deterministic scorer's tier —
            # which then breaks the bootstrap's test runner write and
            # triggers `unverifiable` cascades downstream (item 16). When
            # `codebase` is provided (brownfield), the codebase's detected
            # frameworks already constrain stack choice, so the hard
            # constraint is advisory only ("prefer matching existing stack").
            stack_line = stack_constraint(tier_score.tier.value, app_class)
            if stack_line is not None:
                if codebase is not None:
                    stack_block = (
                        f"\n\n## Tier × Stack Constraint (advisory for brownfield)\n\n"
                        f"For tier={tier_score.tier.value}, app_class={app_class}, "
                        f"the canonical stack family is: {stack_line}.\n"
                        "Brownfield projects MUST keep their existing stack — "
                        "only use this constraint to break ties or fill gaps "
                        "in the detected frameworks above.\n"
                    )
                else:
                    stack_block = (
                        f"\n\n## Tier × Stack Hard Constraint\n\n"
                        f"For tier={tier_score.tier.value}, app_class={app_class}, "
                        f"§4 Tech Stack MUST select a language and framework "
                        f"family from: {stack_line}.\n"
                        "If you believe the tier itself is wrong for this PRD, "
                        "raise it as a concern in §1 (Architectural Trade-offs) "
                        "but do NOT silently switch stacks. Any stack outside "
                        "this list is a contract violation that breaks bootstrap "
                        "and the test runner downstream.\n"
                        + (
                            "\n**Hint block override:** when a `User-Named Stack` "
                            "section appears above, user names take precedence "
                            "over this constraint for the slots the user filled. "
                            "The constraint only governs slots the user left blank.\n"
                            if user_stack_hints
                            else ""
                        )
                    )
            else:
                stack_block = ""

            # Hints come BEFORE the tier-constraint block so the LLM
            # reads user names first.
            stack_block = hint_block + stack_block

        # Faz 1.1 — scope block. When the user has locked an MVP scope,
        # the Architect must treat Phase 1 features as the deliverable for
        # this RFC and explicitly defer Phase 2+ to a separate sub-section
        # of §7 Module Breakdown. Without this, the agent collapses all
        # features into one breakdown — the bug §4 of the self-audit
        # identified as "MVP not structurally present".
        scope_block = ""
        if scope is not None and scope.features:
            scope_block = (
                "\n\n## Locked Scope (HARD — Phase 1 vs Phase 2+ split)\n\n"
                + scope.to_prompt_block()
                + "\n\n**HARD RULE FOR §7 'Module Breakdown'.** Emit a two-tier "
                "table with these EXACT columns:\n\n"
                "| Module | Phase 1 (MVP) | Phase 2+ (Deferred) |\n"
                "|---|---|---|\n"
                "Each row names a module; the Phase 1 cell lists ONLY work that "
                "supports Phase-1 features above; the Phase 2+ cell lists work "
                "that supports deferred features (or `—` if the module has no "
                "deferred work). A module that exists ONLY for deferred features "
                "still appears in the table — its Phase 1 cell is `—`. "
                "The downstream Orchestrator (DAG generation) reads this table "
                "to tag each TaskSpec with a `phase` field; tasks without a "
                "phase signal here get phase=1 by default, which is a silent "
                "scope leak — never leave a Phase 2+ feature without an entry.\n"
            )

        full_system = (
            f"{system_prompt}\n\n"
            f"## L1 Immutable Principles\n\n{principles}\n\n"
            f"## RFC Template (use this exact structure)\n\n{template}\n\n"
            f"## Selected Tier (locked by deterministic scorer)\n\n{tier_brief}"
            f"{tier_doc_block}"
            f"{stack_block}"
            f"{scope_block}"
        )

        codebase_block = ""
        if codebase is not None:
            codebase_block = (
                "## Existing codebase summary\n\n"
                + codebase.to_prompt_text(_CODEBASE_PROMPT_BUDGET_BYTES)
                + "\n\n§7 Module Breakdown MUST list ONLY modules that appear "
                "in the summary above, plus new modules required by the PRD "
                "(mark new modules with `(new)`). §4 Tech Stack MUST match "
                "the detected frameworks and dep manifests.\n\n"
            )

        base_user_prompt = (
            f"Project name: {project_name}\n\n"
            f"{codebase_block}"
            "PRD:\n\n```\n" + prd_markdown + "\n```\n\n"
            "Perform Call 2 only: produce the RFC markdown using the locked tier above. "
            "Mark unfillable fields as `**[NEEDS-INPUT]**` with specific questions. "
            "Do NOT change the tier."
        )

        # Item 40: retry-with-correction loop when §4 Key libraries drifts
        # from locked_stack. Only enforced when a locked_stack is provided
        # (M2 dialog path). Legacy path without locked_stack returns the
        # first draft unchanged.
        drift_corrections: list[str] = []
        phantom_libs: list[str] = []
        response = None
        rfc_text = ""
        for attempt in range(_RFC_DRAFT_MAX_RETRIES):
            user_prompt = base_user_prompt
            if drift_corrections:
                user_prompt = (
                    "## RETRY — locked-stack key_libraries violation on a prior attempt\n\n"
                    + "\n\n".join(drift_corrections)
                    + "\n\n---\n\n"
                    + base_user_prompt
                )
            response = self.llm.call(
                system=full_system,
                user=user_prompt,
                temperature=0.3,
                max_tokens=6000,
            )
            rfc_text = response.text

            if locked_stack is None:
                break

            phantom_libs = _find_phantom_libraries(rfc_text, locked_stack)
            if not phantom_libs:
                break

            allowed = (
                ", ".join(locked_stack.key_libraries)
                or "(empty — locked stack has no key libraries)"
            )
            drift_corrections.append(
                f"Attempt {attempt + 1} drafted §4 'Key libraries' with libraries "
                f"NOT in the locked stack: {', '.join(phantom_libs)}. "
                f"The locked stack's key_libraries are EXACTLY: {allowed}. "
                "Re-emit the RFC with §4 'Key libraries' restricted to that list. "
                "Add nothing. If a phantom library was needed for the architecture, "
                "drop it from §4 and explain the gap as `**[NEEDS-INPUT]**` in §1."
            )
            self.audit.log(
                "architect_rfc_key_libraries_drift",
                project_id=project_id,
                attempt=attempt + 1,
                phantom_libraries=phantom_libs,
                allowed=list(locked_stack.key_libraries),
                **response.audit_fields(),
            )
        else:
            # All retries exhausted without breaking → drift unresolved
            raise RuntimeError(
                f"Architect failed to honor locked stack key_libraries after "
                f"{_RFC_DRAFT_MAX_RETRIES} attempts. Phantom libraries persisted: "
                f"{', '.join(phantom_libs) or '(none — parser edge case)'}. "
                "Inspect the last RFC draft and either refine the stack via "
                "STACK_DIALOG or hand-edit RFC.md."
            )

        self.audit.log(
            "architect_rfc_draft",
            project_id=project_id,
            tier=tier_score.tier.value,
            app_class=app_class,
            stack_constraint=(
                locked_stack.to_prompt_block() if locked_stack is not None
                else stack_constraint(tier_score.tier.value, app_class)
            ),
            used_locked_stack=locked_stack is not None,
            used_scope=scope is not None,
            scope_phase_1_count=(
                len(scope.phase_1_features()) if scope is not None else 0
            ),
            scope_deferred_count=(
                len(scope.deferred_features()) if scope is not None else 0
            ),
            key_libraries_drift_attempts=len(drift_corrections),
            **response.audit_fields(),
        )
        return rfc_text

    @staticmethod
    def _tier_brief(tier_score: TierScore) -> str:
        pros = "\n".join(f"- {p}" for p in tier_score.pros) or "- (none recorded)"
        cons = "\n".join(f"- {c}" for c in tier_score.cons) or "- (none recorded)"
        return (
            f"**Tier:** {tier_score.tier.value} — {tier_score.name}\n"
            f"**Score:** {tier_score.score}\n\n"
            f"**Pros:**\n{pros}\n\n"
            f"**Cons:**\n{cons}\n"
        )

    def select(self, inputs: GoldenPathInputs, project_id: str) -> TierScore:
        score = select_tier(inputs)
        self.audit.log(
            "architect_tier_selected",
            project_id=project_id,
            tier=score.tier.value,
            score=score.score,
            pros=score.pros,
            cons=score.cons,
        )
        return score
