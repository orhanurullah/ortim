# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Babel layer — Turkish brief → structured English intent.

Solves the L1-token-cost-of-non-English problem by normalizing the user's
free-form Turkish into a strict English JSON schema that all downstream
agents consume.

Round-trip TR validation lets the user catch misinterpretation before any
PRD/RFC/code is written.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from ortim.audit import AuditLogger
from ortim.llm import LLMClient
from ortim.memory import MemoryLoader


class StructuredIntent(BaseModel):
    goal: str
    target_users: list[str] = Field(default_factory=list)
    must_have_features: list[str] = Field(default_factory=list)
    nice_to_have_features: list[str] = Field(default_factory=list)
    explicit_non_goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    inferred_compliance: list[str] = Field(default_factory=list)
    inferred_scale: str = "unknown"
    open_questions: list[str] = Field(default_factory=list)
    # Faz 1.2 B-2 fix — explicit tool/framework/language names the user
    # mentioned in the brief. Architect MUST honor these over tier
    # defaults; the dialog-off path bug (proof-point bf761fff02b0) was
    # that the user wrote "Python + FastAPI + SQLite" but the BaaS tier
    # default silently substituted Supabase+PostgreSQL. Keeping this on
    # StructuredIntent (not a new artifact) keeps Babel as the single
    # NLP-extraction layer. Empty list = user named nothing specific.
    user_stack_hints: list[str] = Field(default_factory=list)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[: -3]
    return text.strip()


# Faz 1.2 B-5 fix — deterministic app_class inference from user-named
# stack hints. Architect Call 1 LLM defaults to "web" when the PRD has
# no mobile/desktop signal, even when the brief explicitly mentioned
# Flutter / Tauri / React Native (proof-point 45ed19809dec: Flutter habit
# tracker → tier T2 BaaS instead of M1).
#
# Two flavors of hint exist:
#   * Framework names — only meaningful for a specific app_class
#     (Flutter ⇒ mobile, Tauri ⇒ desktop).
#   * Generic platform tokens — user said "mobil uygulama" / "Android için"
#     without naming a framework. These were previously invisible to the
#     classifier and resulted in greenfield state.json being seeded with
#     app_class="web" by default.
_MOBILE_FRAMEWORK_HINTS = (
    "flutter",
    "react native",
    "react-native",
    "ionic",
    "capacitor",
    "swiftui",
    "jetpack compose",
    "xamarin",
    "kotlin multiplatform",
)
_DESKTOP_FRAMEWORK_HINTS = (
    "tauri",
    "electron",
    "wails",
    "qt",
    "gtk",
    "wpf",
    "winforms",
    "avalonia",
)
_MOBILE_GENERIC_HINTS = (
    "mobile app",
    "mobil uygulama",
    "mobile application",
    "android app",
    "android uygulaması",
    "ios app",
    "iphone app",
    "ipad app",
    "play store",
    "app store",
    "google play",
    "mobil platform",
)
# Single-token platform terms — matched as whole words to avoid false
# positives ("ios" inside "kiosks", "tablet" inside "tabletop"). The
# tuple holds the canonical lowercase form; `_match_whole_word` does
# the boundary check.
_MOBILE_GENERIC_TOKENS = (
    "android",
    "ios",
    "iphone",
    "ipad",
    "tablet",
)
_DESKTOP_GENERIC_HINTS = (
    "desktop app",
    "masaüstü uygulama",
    "masaüstü uygulaması",
    "windows app",
    "windows uygulaması",
    "macos app",
    "mac app",
    "linux app",
    "desktop application",
    "tray app",
    "system tray",
)
_DESKTOP_GENERIC_TOKENS = (
    "desktop",
    "masaüstü",
)

_MOBILE_HINTS = _MOBILE_FRAMEWORK_HINTS + _MOBILE_GENERIC_HINTS
_DESKTOP_HINTS = _DESKTOP_FRAMEWORK_HINTS + _DESKTOP_GENERIC_HINTS


def _match_whole_word(blob: str, token: str) -> bool:
    """Word-boundary check that treats only alphanumerics+underscore as
    word characters (the default `re.\\b` semantics). Used for single
    tokens like "ios" so they don't fire inside "kiosks"."""
    import re

    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", blob) is not None


def app_class_from_hints(hints: list[str]) -> str | None:
    """Return `"mobile"`, `"desktop"`, or `None` from explicit stack names.

    None means "no signal" — caller must keep the LLM's choice. Mobile
    and desktop signals win deterministically because the user named a
    framework that only makes sense for that app_class. Web is never
    returned (the absence of a mobile/desktop signal is not evidence of
    a web choice — could be a CLI / API / static site).
    """
    if not hints:
        return None
    blob = " ".join(s.lower() for s in hints)
    for kw in _MOBILE_HINTS:
        if kw in blob:
            return "mobile"
    for kw in _DESKTOP_HINTS:
        if kw in blob:
            return "desktop"
    for tok in _MOBILE_GENERIC_TOKENS:
        if _match_whole_word(blob, tok):
            return "mobile"
    for tok in _DESKTOP_GENERIC_TOKENS:
        if _match_whole_word(blob, tok):
            return "desktop"
    return None


def app_class_from_brief(brief: str) -> str | None:
    """Scan a free-form (Turkish) brief for app_class signals.

    Mirrors `app_class_from_hints` but operates on raw user text so the
    classifier fires even when the user says "mobil uygulama" without
    naming a framework. Consumed by `ortim.workspace.init.init_project`
    so state.json is seeded with the right value before Babel runs.

    Multi-word phrases are matched as substrings; single tokens use word
    boundaries (see `_match_whole_word`). Mobile signals win over desktop
    when both appear (matches `app_class_from_hints` priority — mobile is
    statistically more common in the ortim corpus).
    """
    if not brief:
        return None
    blob = brief.lower()
    for kw in _MOBILE_HINTS:
        if kw in blob:
            return "mobile"
    for kw in _DESKTOP_HINTS:
        if kw in blob:
            return "desktop"
    for tok in _MOBILE_GENERIC_TOKENS:
        if _match_whole_word(blob, tok):
            return "mobile"
    for tok in _DESKTOP_GENERIC_TOKENS:
        if _match_whole_word(blob, tok):
            return "desktop"
    return None


class BabelLayer:
    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryLoader,
        audit: AuditLogger,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.audit = audit

    def extract(self, turkish_brief: str, project_id: str) -> StructuredIntent:
        system_prompt = self.memory.load_agent_prompt("babel")
        glossary = self.memory.load_glossary()
        if glossary:
            system_prompt = f"{system_prompt}\n\n## Glossary (TR-EN)\n\n{glossary}"

        user_prompt = (
            "Turkish brief from user:\n\n"
            f"```\n{turkish_brief}\n```\n\n"
            "Extract structured intent. Output ONLY a valid JSON object matching the "
            "StructuredIntent schema. No prose, no markdown fences, no explanation."
        )

        response = self.llm.call(
            system=system_prompt,
            user=user_prompt,
            temperature=0.0,
            max_tokens=2000,
        )

        cleaned = _strip_code_fences(response.text)
        try:
            intent = StructuredIntent.model_validate_json(cleaned)
        except (ValidationError, ValueError) as e:
            self.audit.log(
                "babel_extract_failed",
                project_id=project_id,
                error=str(e),
                raw=cleaned[:500],
                **response.audit_fields(),
            )
            raise

        self.audit.log(
            "babel_extract_ok",
            project_id=project_id,
            intent=intent.model_dump(),
            **response.audit_fields(),
        )
        return intent

    def round_trip(
        self, intent: StructuredIntent, project_id: str, brief: str | None = None
    ) -> str:
        """Summarize the intent back in the user's language so they can confirm."""
        language_rule = (
            "Write the summary in the same language as the original brief below."
            if brief
            else "Write the summary in English."
        )
        brief_block = f"Original brief:\n{brief}\n\n" if brief else ""
        response = self.llm.call(
            system=(
                "You translate structured English intent JSON into clear, concise "
                f"prose for user validation. {language_rule} Maximum 150 words. "
                "Use bullet points where it helps clarity."
            ),
            user=(
                f"{brief_block}"
                "Summarize the following intent JSON so the user can validate it. "
                "Call out missing or ambiguous points explicitly.\n\n"
                f"{intent.model_dump_json(indent=2)}"
            ),
            temperature=0.2,
            max_tokens=600,
        )
        self.audit.log(
            "babel_round_trip",
            project_id=project_id,
            **response.audit_fields(),
        )
        return response.text
