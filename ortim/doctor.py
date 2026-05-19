# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Environment health check for the Ortim runtime.

Read-only by design — `ortim doctor` reports gaps and prints fix hints,
but does not modify the environment. Three categories:

  * **required** — system cannot operate at all without these
    (Python version, workspace/audit dirs, L1 principles, agent prompts)
  * **recommended** — major features off without these
    (LLM API keys, git, skill files, tier templates)
  * **optional** — only matters for specific tier × app_class
    (Node/npm for web, Flutter for mobile, Cargo for Rust, Go)

API keys are explicitly **recommended**, not required, because several
commands operate without an LLM (`score-tier`, `states`, `list-projects`,
`status`, `gates`, `retro`, `drift-check`, `doctor` itself). The runtime
fails loudly at LLM call time if keys are missing — doctor surfaces the
gap proactively but doesn't block a key-free workflow.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

CAT_REQUIRED = "required"
CAT_RECOMMENDED = "recommended"
CAT_OPTIONAL = "optional"

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_WARNING = "warning"


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str
    category: str
    fix_hint: str = ""


@dataclass(frozen=True)
class DoctorReport:
    checks: list[DoctorCheck] = field(default_factory=list)

    @property
    def required_failures(self) -> list[DoctorCheck]:
        return [
            c for c in self.checks
            if c.category == CAT_REQUIRED and c.status != STATUS_OK
        ]

    @property
    def recommended_misses(self) -> list[DoctorCheck]:
        return [
            c for c in self.checks
            if c.category == CAT_RECOMMENDED and c.status != STATUS_OK
        ]

    @property
    def optional_misses(self) -> list[DoctorCheck]:
        return [
            c for c in self.checks
            if c.category == CAT_OPTIONAL and c.status != STATUS_OK
        ]

    @property
    def exit_code(self) -> int:
        """0 clean; 2 recommended gaps; 3 required failures.
        Optional gaps never raise the exit code on their own."""
        if self.required_failures:
            return 3
        if self.recommended_misses:
            return 2
        return 0


def _which_version(binary: str, version_flag: str = "--version") -> str | None:
    """Return the trimmed first line of `<binary> <version_flag>` output,
    or None if the binary is not on PATH or the call fails fast."""
    path = shutil.which(binary)
    if path is None:
        return None
    try:
        # `text=True` would inherit the platform codec (cp1254 on TR
        # Windows) and throw on any non-mapped byte some binaries emit.
        # Decode as bytes, then UTF-8 with replace fallback — version
        # strings are ASCII in practice so this never loses signal.
        out = subprocess.run(
            [path, version_flag],
            capture_output=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    raw = (out.stdout or out.stderr or b"")
    text = raw.decode("utf-8", errors="replace").strip()
    return text.splitlines()[0].strip() if text else "(no version output)"


def check_python_version() -> DoctorCheck:
    major, minor = sys.version_info[:2]
    detail = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if (major, minor) >= (3, 11):
        return DoctorCheck("Python 3.11+", STATUS_OK, detail, CAT_REQUIRED)
    return DoctorCheck(
        "Python 3.11+",
        STATUS_MISSING,
        f"{detail} (< 3.11)",
        CAT_REQUIRED,
        fix_hint="install Python 3.11 or newer; re-create the venv",
    )


def check_workspace_dir(workspace_root: Path) -> DoctorCheck:
    try:
        workspace_root.mkdir(parents=True, exist_ok=True)
        probe = workspace_root / ".doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return DoctorCheck(
            "Workspace dir",
            STATUS_MISSING,
            f"{workspace_root} (not writable: {e})",
            CAT_REQUIRED,
            fix_hint=f"ensure write permission on {workspace_root}",
        )
    return DoctorCheck(
        "Workspace dir",
        STATUS_OK,
        f"{workspace_root} (writable)",
        CAT_REQUIRED,
    )


def check_audit_log_dir(repo_root: Path) -> DoctorCheck:
    audit_path = Path(
        os.getenv("AUDIT_LOG_PATH", str(repo_root / "ortim" / "audit" / "decisions.jsonl"))
    )
    audit_dir = audit_path.parent
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        probe = audit_dir / ".doctor_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return DoctorCheck(
            "Audit log dir",
            STATUS_MISSING,
            f"{audit_dir} (not writable: {e})",
            CAT_REQUIRED,
            fix_hint=(
                f"ensure write permission on {audit_dir}, or set "
                "AUDIT_LOG_PATH to a writable location"
            ),
        )
    return DoctorCheck(
        "Audit log dir",
        STATUS_OK,
        f"{audit_dir} (writable)",
        CAT_REQUIRED,
    )


def check_l1_principles(repo_root: Path) -> DoctorCheck:
    path = repo_root / "docs" / "principles" / "core.md"
    if path.exists() and path.stat().st_size > 0:
        return DoctorCheck(
            "L1 principles file",
            STATUS_OK,
            str(path.relative_to(repo_root)),
            CAT_REQUIRED,
        )
    return DoctorCheck(
        "L1 principles file",
        STATUS_MISSING,
        f"{path.relative_to(repo_root) if repo_root in path.parents else path} not found",
        CAT_REQUIRED,
        fix_hint="restore docs/principles/core.md from version control",
    )


_REQUIRED_AGENT_PROMPTS = (
    "babel.md",
    "worker.md",
    "reviewer.md",
    "architect.md",
    "orchestrator.md",
)


def check_agent_prompts(repo_root: Path) -> DoctorCheck:
    agents_dir = repo_root / "agents"
    if not agents_dir.exists():
        return DoctorCheck(
            "Agent prompts",
            STATUS_MISSING,
            f"{agents_dir} dir not found",
            CAT_REQUIRED,
            fix_hint="restore agents/*.md from version control",
        )
    missing = [n for n in _REQUIRED_AGENT_PROMPTS if not (agents_dir / n).exists()]
    if missing:
        return DoctorCheck(
            "Agent prompts",
            STATUS_MISSING,
            f"missing: {', '.join(missing)}",
            CAT_REQUIRED,
            fix_hint="restore the listed prompt files from version control",
        )
    total = len(list(agents_dir.glob("*.md")))
    return DoctorCheck(
        "Agent prompts",
        STATUS_OK,
        f"{total} found ({len(_REQUIRED_AGENT_PROMPTS)} core + extras)",
        CAT_REQUIRED,
    )


def _check_api_key(env_name: str, role_hint: str) -> DoctorCheck:
    raw = os.environ.get(env_name, "")
    if raw.strip():
        return DoctorCheck(
            env_name,
            STATUS_OK,
            f"set (length {len(raw)})",
            CAT_RECOMMENDED,
        )
    return DoctorCheck(
        env_name,
        STATUS_MISSING,
        f"not set — {role_hint} commands will fail at LLM call time",
        CAT_RECOMMENDED,
        fix_hint=f"export {env_name}=... in .env or your shell",
    )


def check_anthropic_key() -> DoctorCheck:
    return _check_api_key(
        "ANTHROPIC_API_KEY",
        "Anthropic-backed (Architect / Security / default)",
    )


def check_deepseek_key() -> DoctorCheck:
    return _check_api_key(
        "DEEPSEEK_API_KEY",
        "DeepSeek-backed (Babel / Worker / Reviewer when routing applies)",
    )


def check_active_provider() -> DoctorCheck:
    """Report which LLM provider would be selected for an LLM call right
    now, and whether the matching credential is present.

    This is the one check operators actually need when an LLM call fails
    — `ANTHROPIC_API_KEY: MISS` is noise if the operator deliberately
    picked DeepSeek or Ollama. Surfacing the resolved provider + source
    + key status in a single line removes the guesswork.
    """
    try:
        from ortim.config import env_source
        from ortim.llm.providers import resolve_provider
    except Exception as e:
        return DoctorCheck(
            "Active LLM provider",
            STATUS_WARNING,
            f"could not resolve: {type(e).__name__}: {e}",
            CAT_RECOMMENDED,
        )

    try:
        provider = resolve_provider()
    except Exception as e:
        return DoctorCheck(
            "Active LLM provider",
            STATUS_MISSING,
            f"resolution failed: {e}",
            CAT_RECOMMENDED,
            fix_hint="run `ortim config init` to pick a valid provider",
        )

    source = env_source("LLM_PROVIDER")
    if provider.api_key_env is None:
        return DoctorCheck(
            "Active LLM provider",
            STATUS_OK,
            f"{provider.name} (source: {source}; no key required)",
            CAT_RECOMMENDED,
        )
    key_set = bool(os.environ.get(provider.api_key_env, "").strip())
    if key_set:
        return DoctorCheck(
            "Active LLM provider",
            STATUS_OK,
            f"{provider.name} (source: {source}; {provider.api_key_env} set)",
            CAT_RECOMMENDED,
        )
    return DoctorCheck(
        "Active LLM provider",
        STATUS_MISSING,
        f"{provider.name} selected (source: {source}) but "
        f"{provider.api_key_env} is not set",
        CAT_RECOMMENDED,
        fix_hint=(
            f"run `ortim config set-key {provider.name}`, export "
            f"{provider.api_key_env}=..., or pick another provider "
            f"with `ortim config set-provider`"
        ),
    )


def check_git() -> DoctorCheck:
    version = _which_version("git")
    if version:
        return DoctorCheck("Git", STATUS_OK, version, CAT_RECOMMENDED)
    return DoctorCheck(
        "Git",
        STATUS_MISSING,
        "not installed — branch isolation, worktree mode, and commit "
        "hooks all degrade",
        CAT_RECOMMENDED,
        fix_hint="install git and ensure it is on PATH",
    )


def check_skills_dir(repo_root: Path) -> DoctorCheck:
    skills_dir = repo_root / "skills"
    if not skills_dir.exists():
        return DoctorCheck(
            "Skills directory",
            STATUS_MISSING,
            f"{skills_dir} not found",
            CAT_RECOMMENDED,
            fix_hint="restore skills/ from version control or accept M3 disabled",
        )
    md_count = sum(1 for _ in skills_dir.rglob("*.md"))
    if md_count == 0:
        return DoctorCheck(
            "Skills directory",
            STATUS_WARNING,
            f"{skills_dir} present but empty",
            CAT_RECOMMENDED,
            fix_hint="add a skill file under skills/<scope>/<name>.md",
        )
    return DoctorCheck(
        "Skills directory",
        STATUS_OK,
        f"{md_count} skill file(s)",
        CAT_RECOMMENDED,
    )


def check_tier_templates() -> DoctorCheck:
    """The bootstrap module owns per-tier scaffolding. We probe its
    `_FRAMEWORK_PACKAGES` registry to confirm the T2/T4 web path is
    wired — that's the path 90% of current proof-points exercise."""
    try:
        from ortim.architecture.bootstrap import _FRAMEWORK_PACKAGES
    except Exception as e:
        return DoctorCheck(
            "Tier templates",
            STATUS_MISSING,
            f"bootstrap module failed to import: {type(e).__name__}",
            CAT_RECOMMENDED,
            fix_hint="restore ortim/architecture/bootstrap.py",
        )
    if not _FRAMEWORK_PACKAGES:
        return DoctorCheck(
            "Tier templates",
            STATUS_WARNING,
            "_FRAMEWORK_PACKAGES empty — bootstrap will not install deps",
            CAT_RECOMMENDED,
        )
    return DoctorCheck(
        "Tier templates",
        STATUS_OK,
        f"{len(_FRAMEWORK_PACKAGES)} framework(s) registered",
        CAT_RECOMMENDED,
    )


def check_node() -> DoctorCheck:
    version = _which_version("node")
    if version:
        return DoctorCheck(
            "Node.js",
            STATUS_OK,
            f"{version} (T1-T4 web)",
            CAT_OPTIONAL,
        )
    return DoctorCheck(
        "Node.js",
        STATUS_MISSING,
        "not installed (T1-T4 web tier bootstrap)",
        CAT_OPTIONAL,
        fix_hint="install Node.js LTS from nodejs.org if you target web tiers",
    )


def check_npm() -> DoctorCheck:
    version = _which_version("npm")
    if version:
        return DoctorCheck(
            "npm",
            STATUS_OK,
            f"{version} (T1-T4 web)",
            CAT_OPTIONAL,
        )
    return DoctorCheck(
        "npm",
        STATUS_MISSING,
        "not installed (ships with Node.js LTS)",
        CAT_OPTIONAL,
    )


def check_flutter() -> DoctorCheck:
    version = _which_version("flutter")
    if version:
        return DoctorCheck(
            "Flutter",
            STATUS_OK,
            f"{version} (M0-M2 mobile)",
            CAT_OPTIONAL,
        )
    return DoctorCheck(
        "Flutter",
        STATUS_MISSING,
        "not installed (M0-M2 mobile tier)",
        CAT_OPTIONAL,
        fix_hint="install Flutter SDK if you target mobile tiers",
    )


def check_cargo() -> DoctorCheck:
    version = _which_version("cargo")
    if version:
        return DoctorCheck(
            "Cargo",
            STATUS_OK,
            f"{version} (Tauri D1, Rust)",
            CAT_OPTIONAL,
        )
    return DoctorCheck(
        "Cargo",
        STATUS_MISSING,
        "not installed (D1 Tauri, Rust)",
        CAT_OPTIONAL,
        fix_hint="install Rust via rustup if you target Tauri/Rust",
    )


def check_go() -> DoctorCheck:
    version = _which_version("go", "version")
    if version:
        return DoctorCheck(
            "Go",
            STATUS_OK,
            f"{version} (Go-backed tiers)",
            CAT_OPTIONAL,
        )
    return DoctorCheck(
        "Go",
        STATUS_MISSING,
        "not installed",
        CAT_OPTIONAL,
    )


def check_python_venv() -> DoctorCheck:
    """Soft signal: we're inside a venv when sys.prefix differs from
    sys.base_prefix. Outside a venv, pip install -e . pollutes the
    system Python — a warning, not a failure."""
    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        return DoctorCheck(
            "Python venv",
            STATUS_OK,
            f"active ({sys.prefix})",
            CAT_OPTIONAL,
        )
    return DoctorCheck(
        "Python venv",
        STATUS_WARNING,
        "not in a virtual environment",
        CAT_OPTIONAL,
        fix_hint="create one with `python -m venv .venv` and activate it",
    )


def run_all_checks(
    *,
    workspace_root: Path,
    repo_root: Path,
) -> DoctorReport:
    """Run every check in display order. Each check is independent —
    one failure does not abort the rest, so the report is always complete."""
    checks = [
        # Required
        check_python_version(),
        check_workspace_dir(workspace_root),
        check_audit_log_dir(repo_root),
        check_l1_principles(repo_root),
        check_agent_prompts(repo_root),
        # Recommended
        check_active_provider(),
        check_anthropic_key(),
        check_deepseek_key(),
        check_git(),
        check_skills_dir(repo_root),
        check_tier_templates(),
        # Optional
        check_node(),
        check_npm(),
        check_flutter(),
        check_cargo(),
        check_go(),
        check_python_venv(),
    ]
    return DoctorReport(checks=checks)


def to_json_dict(report: DoctorReport) -> dict:
    return {
        "exit_code": report.exit_code,
        "required_failures": len(report.required_failures),
        "recommended_misses": len(report.recommended_misses),
        "optional_misses": len(report.optional_misses),
        "checks": [
            {
                "name": c.name,
                "status": c.status,
                "category": c.category,
                "detail": c.detail,
                "fix_hint": c.fix_hint,
            }
            for c in report.checks
        ],
    }
