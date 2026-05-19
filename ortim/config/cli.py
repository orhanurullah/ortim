# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Typer subapp for `ortim config <cmd>`.

Mounted into the main app in `ortim.main`. Commands:

  * `init`          — interactive provider/model/key wizard
  * `show`          — print resolved config + source per field
  * `path`          — print config file path
  * `set-provider`  — non-interactive provider write
  * `set-model`     — non-interactive model write
  * `set-key`       — prompted (hidden) API key write per provider
  * `set-role`      — role-specific provider/model override

Each `set-*` command performs a load → mutate → save roundtrip so other
fields persist unchanged. Missing config file is treated as an empty
config, never an error.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ortim.config.store import (
    PROVIDER_BASE_URL_ENV,
    PROVIDER_KEY_ENV,
    Config,
    default_path,
    env_source,
    load,
    save,
)
from ortim.llm.providers import PROVIDERS

console = Console()

config_app = typer.Typer(
    help="Persistent user config — provider, model, API keys.",
    no_args_is_help=True,
)


def _load_or_empty() -> Config:
    """Load existing config or return a blank one. Used by every
    `set-*` command so a missing file isn't an error — first write
    creates it."""
    return load() or Config()


def _provider_choices() -> list[str]:
    return sorted(PROVIDERS.keys())


def _validate_provider(name: str) -> str:
    """Lowercase + validate against the known provider set. Raises
    typer.BadParameter so the CLI shows a clean error, not a stack."""
    norm = name.strip().lower()
    if norm not in PROVIDERS:
        valid = ", ".join(_provider_choices())
        raise typer.BadParameter(
            f"unknown provider {name!r}; valid: {valid}"
        )
    return norm


@config_app.command("init")
def init() -> None:
    """Interactive wizard — provider, model, API key.

    Overwrites the relevant fields on the existing config; preserves
    unrelated fields (e.g., role overrides) untouched. Safe to re-run.
    """
    cfg = _load_or_empty()
    target = default_path()
    console.print(f"\n[bold]Ortim config wizard[/bold] — writing to [cyan]{target}[/cyan]\n")

    providers = _provider_choices()
    console.print("[bold]1/3 — Choose default provider:[/bold]")
    for idx, name in enumerate(providers, start=1):
        info = PROVIDERS[name]
        # Surface the "no key needed" property for local providers
        # since that is the whole reason someone would pick ollama.
        key_hint = "no API key needed" if info.api_key_env is None else f"requires {info.api_key_env}"
        console.print(f"  {idx}) [cyan]{name}[/cyan]  ({key_hint})")
    current_default = cfg.default_provider or "anthropic"
    default_idx = providers.index(current_default) + 1 if current_default in providers else 1
    raw = typer.prompt(f"Choice [1-{len(providers)}]", default=str(default_idx))
    try:
        choice_idx = int(raw)
        provider = providers[choice_idx - 1]
    except (ValueError, IndexError):
        provider = _validate_provider(raw)
    cfg.default_provider = provider
    provider_cfg = PROVIDERS[provider]
    console.print(f"  → [green]{provider}[/green]\n")

    console.print("[bold]2/3 — Default model[/bold] (press Enter for provider default):")
    model = typer.prompt(
        f"Model [{provider_cfg.default_model}]",
        default=provider_cfg.default_model,
        show_default=False,
    ).strip()
    cfg.default_model = model or None
    console.print(f"  → [green]{model or provider_cfg.default_model}[/green]\n")

    console.print("[bold]3/3 — API key[/bold]")
    if provider_cfg.api_key_env is None:
        console.print(f"  [dim]{provider} is local; no key required.[/dim]\n")
    else:
        existing = cfg.provider_keys.get(provider)
        if existing:
            console.print(
                f"  [dim]A key for {provider} is already stored "
                f"(length {len(existing)}). Press Enter to keep, "
                f"or paste a new one.[/dim]"
            )
        key = typer.prompt(
            f"{provider_cfg.api_key_env}",
            default="" if not existing else "*" * 8,
            hide_input=True,
            show_default=False,
        ).strip()
        # Empty input keeps the existing key; "*" placeholder also kept.
        if key and not set(key) <= {"*"}:
            cfg.provider_keys[provider] = key
            console.print("  → [green]key stored[/green]\n")
        elif existing:
            console.print("  → [dim]key unchanged[/dim]\n")

    written = save(cfg)
    console.print(f"[green]Saved.[/green] Run [cyan]ortim config show[/cyan] to verify.\n")
    console.print(f"[dim]Path: {written}[/dim]")


@config_app.command("show")
def show() -> None:
    """Print the current resolved config + per-field source.

    `source` is one of:
      * `config` — populated from `~/.ortim/config.toml`
      * `env`    — set in `os.environ` (shell or `.env`)
      * `default` — neither; hardcoded fallback will apply
    """
    import os

    cfg = load()
    path = default_path()
    console.print(f"\n[bold]Ortim config[/bold] [dim]({path})[/dim]")
    if cfg is None:
        console.print("  [yellow]No config file yet. Run `ortim config init`.[/yellow]\n")
    else:
        console.print("")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Setting")
    table.add_column("Value")
    table.add_column("Source")

    def _row(label: str, env_name: str, mask: bool = False) -> None:
        val = os.environ.get(env_name, "")
        if not val:
            shown = "[dim](unset)[/dim]"
        elif mask:
            shown = f"set (length {len(val)})"
        else:
            shown = val
        table.add_row(label, shown, env_source(env_name))

    _row("default provider", "LLM_PROVIDER")
    _row("default model", "DEFAULT_MODEL")
    for prov, env in sorted(PROVIDER_KEY_ENV.items()):
        _row(f"{prov} api key", env, mask=True)
    for prov, env in sorted(PROVIDER_BASE_URL_ENV.items()):
        _row(f"{prov} base url", env)

    # Role overrides — only show ones that are actually set.
    role_envs = sorted({k.upper() for k in (cfg.roles if cfg else {})} | {
        k for k in os.environ if k.endswith(("_PROVIDER", "_MODEL"))
        and k not in {"LLM_PROVIDER", "DEFAULT_MODEL"}
    })
    for env_name in role_envs:
        _row(env_name.lower().replace("_", " "), env_name)

    console.print(table)
    console.print("")


@config_app.command("path")
def path_cmd() -> None:
    """Print the config file path (honors `ORTIM_CONFIG` env override)."""
    print(default_path())


@config_app.command("set-provider")
def set_provider(
    name: str = typer.Argument(..., help="anthropic | deepseek | ollama"),
) -> None:
    """Set the default provider. Equivalent to `LLM_PROVIDER` env."""
    norm = _validate_provider(name)
    cfg = _load_or_empty()
    cfg.default_provider = norm
    target = save(cfg)
    console.print(f"[green]default provider →[/green] {norm}  [dim]({target})[/dim]")


@config_app.command("set-model")
def set_model(
    model: str = typer.Argument(..., help="Model id (e.g. claude-opus-4-7)"),
) -> None:
    """Set the default model. Equivalent to `DEFAULT_MODEL` env."""
    cfg = _load_or_empty()
    cfg.default_model = model.strip() or None
    target = save(cfg)
    console.print(f"[green]default model →[/green] {model}  [dim]({target})[/dim]")


@config_app.command("set-key")
def set_key(
    provider: str = typer.Argument(..., help="Provider whose key to set."),
    key: str = typer.Option(
        None, "--key", "-k",
        help="Provide the key inline. Omit to be prompted (hidden input).",
    ),
) -> None:
    """Store an API key for a provider. Prompts with hidden input when
    --key is omitted so the key never lands in shell history."""
    norm = _validate_provider(provider)
    pc = PROVIDERS[norm]
    if pc.api_key_env is None:
        console.print(f"[yellow]{norm} is local; no API key needed.[/yellow]")
        raise typer.Exit(code=0)
    if key is None:
        key = typer.prompt(f"{pc.api_key_env}", hide_input=True)
    key = key.strip()
    if not key:
        console.print("[red]Empty key; nothing written.[/red]")
        raise typer.Exit(code=1)
    cfg = _load_or_empty()
    cfg.provider_keys[norm] = key
    target = save(cfg)
    console.print(
        f"[green]{pc.api_key_env} stored[/green] for {norm}  "
        f"[dim]({target})[/dim]"
    )


@config_app.command("set-role")
def set_role(
    role: str = typer.Argument(
        ...,
        help="Agent role (e.g. architect, babel, worker, reviewer).",
    ),
    provider: str = typer.Option(
        None, "--provider", "-p", help="Provider override for this role."
    ),
    model: str = typer.Option(
        None, "--model", "-m", help="Model override for this role."
    ),
    clear: bool = typer.Option(
        False, "--clear", help="Remove the role override instead of setting it."
    ),
) -> None:
    """Pin a role to a specific provider/model. Equivalent to the
    `<ROLE>_PROVIDER` / `<ROLE>_MODEL` env vars consulted by the router.
    """
    role_norm = role.strip().lower()
    if not role_norm:
        raise typer.BadParameter("role name is required")
    cfg = _load_or_empty()
    prov_key = f"{role_norm}_provider"
    model_key = f"{role_norm}_model"
    if clear:
        cfg.roles.pop(prov_key, None)
        cfg.roles.pop(model_key, None)
        target = save(cfg)
        console.print(
            f"[green]cleared[/green] role override for {role_norm}  "
            f"[dim]({target})[/dim]"
        )
        return
    if not (provider or model):
        raise typer.BadParameter(
            "pass --provider, --model, or both (or --clear to remove)."
        )
    if provider:
        cfg.roles[prov_key] = _validate_provider(provider)
    if model:
        cfg.roles[model_key] = model.strip()
    target = save(cfg)
    console.print(
        f"[green]role[/green] {role_norm}: "
        f"provider={cfg.roles.get(prov_key, '(unchanged)')} "
        f"model={cfg.roles.get(model_key, '(unchanged)')}  "
        f"[dim]({target})[/dim]"
    )
