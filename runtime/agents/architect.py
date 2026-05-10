# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Architect agent — PRD → GoldenPathInputs (LLM) → tier (deterministic) → RFC (LLM).

The split is intentional: an LLM cannot pick the tier, only describe what
the PRD asks for. The scorer (deterministic, rule-based) picks the tier.
This prevents "sounds enterprise so let's microservice" failure modes.
"""

from __future__ import annotations

from runtime.architecture import (
    GoldenPathInputs,
    TierScore,
    select_tier,
    stack_constraint,
)
from runtime.audit import AuditLogger
from runtime.babel.intent import _strip_code_fences
from runtime.codebase import CodebaseSummary
from runtime.llm import LLMClient
from runtime.memory import MemoryLoader

_CODEBASE_PROMPT_BUDGET_BYTES = 2000


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

        # Item 17 fix: thread the (tier, app_class) language/framework
        # constraint into the prompt so Architect Call 2 cannot pick a
        # stack inconsistent with the deterministic scorer's tier — which
        # then breaks the bootstrap's test runner write and triggers
        # `unverifiable` cascades downstream (item 16). When `codebase` is
        # provided (brownfield), the codebase's detected frameworks
        # already constrain stack choice, so the hard constraint is
        # advisory only ("prefer matching existing stack").
        stack_line = stack_constraint(tier_score.tier.value, app_class)
        if stack_line is not None:
            if codebase is not None:
                stack_block = (
                    f"\n\n## Tier × Stack Constraint (advisory for brownfield)\n\n"
                    f"For tier={tier_score.tier.value}, app_class={app_class}, "
                    f"the canonical stack family is: {stack_line}.\n"
                    "Brownfield projects MUST keep their existing stack — only "
                    "use this constraint to break ties or fill gaps in the "
                    "detected frameworks above.\n"
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
                )
        else:
            stack_block = ""

        full_system = (
            f"{system_prompt}\n\n"
            f"## L1 Immutable Principles\n\n{principles}\n\n"
            f"## RFC Template (use this exact structure)\n\n{template}\n\n"
            f"## Selected Tier (locked by deterministic scorer)\n\n{tier_brief}"
            f"{tier_doc_block}"
            f"{stack_block}"
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

        user_prompt = (
            f"Project name: {project_name}\n\n"
            f"{codebase_block}"
            "PRD:\n\n```\n" + prd_markdown + "\n```\n\n"
            "Perform Call 2 only: produce the RFC markdown using the locked tier above. "
            "Mark unfillable fields as `**[NEEDS-INPUT]**` with specific questions. "
            "Do NOT change the tier."
        )

        response = self.llm.call(
            system=full_system,
            user=user_prompt,
            temperature=0.3,
            max_tokens=6000,
        )

        self.audit.log(
            "architect_rfc_draft",
            project_id=project_id,
            tier=tier_score.tier.value,
            app_class=app_class,
            stack_constraint=stack_line,
            **response.audit_fields(),
        )
        return response.text

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
