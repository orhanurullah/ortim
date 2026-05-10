# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Markdown-based knowledge loader.

L1 principles, templates, glossary, and agent system prompts live as markdown
under repo_root/docs and repo_root/agents. Loader concatenates files in
deterministic alphabetical order.
"""

from __future__ import annotations

from pathlib import Path


class MemoryLoader:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def _concat_md(self, directory: Path) -> str:
        if not directory.exists():
            return ""
        chunks: list[str] = []
        for md in sorted(directory.glob("*.md")):
            chunks.append(md.read_text(encoding="utf-8"))
        return "\n\n---\n\n".join(chunks)

    def load_l1_principles(self) -> str:
        return self._concat_md(self.repo_root / "docs" / "principles")

    def load_glossary(self) -> str:
        return self._concat_md(self.repo_root / "docs" / "glossary")

    def load_template(self, name: str) -> str:
        path = self.repo_root / "docs" / "templates" / f"{name}.template.md"
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")
        return path.read_text(encoding="utf-8")

    def load_agent_prompt(self, name: str) -> str:
        path = self.repo_root / "agents" / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Agent prompt not found: {path}")
        return path.read_text(encoding="utf-8")

    def load_tier_doc(self, tier_value: str) -> str:
        """Load the golden-path doc for a Tier.value (e.g. 'T4', 'M1', 'D1').

        Returns empty string if no doc exists — callers must tolerate the
        miss (older tiers may lack docs, and we don't want to crash RFC
        drafting just because someone added a Tier enum without a doc).
        """
        directory = self.repo_root / "docs" / "golden-paths"
        if not directory.exists():
            return ""
        for md in directory.glob(f"{tier_value}-*.md"):
            return md.read_text(encoding="utf-8")
        return ""
