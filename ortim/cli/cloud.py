# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""CLI: `ortim cloud` — Observer layer (login / link / sync / policy).

Never blocks the local pipeline: if the cloud is unreachable, `sync` prints
a warning and exits 0 (offline-safe). Pushed data is redacted metadata;
source code is never sent.
"""

from __future__ import annotations

import typer

from ortim.cli._globals import _resolve_project, console
from ortim.cloud import CloudClient, CloudError
from ortim.cloud import config as cloud_config
from ortim.cloud import policy as cloud_policy
from ortim.cloud import sync as cloud_sync

cloud_app = typer.Typer(help="Ortim Cloud — audit/governance sync")


def _client(require_auth: bool = True) -> tuple[CloudClient, cloud_config.CloudConfig]:
    cfg = cloud_config.load()
    if require_auth and not cfg.token:
        console.print("[red]Not logged in.[/red] Run [cyan]ortim cloud login[/cyan].")
        raise typer.Exit(1)
    return CloudClient(cfg.base_url, cfg.token), cfg


def _device_login(client: CloudClient, cfg: cloud_config.CloudConfig) -> None:
    """Browser device-code flow (RFC 8628): start → confirm in browser → poll.

    This is the default login because most platform accounts are created
    with Google sign-in and have no password at all.
    """
    import time
    import webbrowser

    try:
        start = client.device_start()
    except CloudError as e:
        console.print(f"[red]Could not start the login flow:[/red] {e}")
        raise typer.Exit(1)

    user_code = str(start.get("userCode", ""))
    device_code = str(start.get("deviceCode", ""))
    if not user_code or not device_code:
        console.print(f"[red]Unexpected response from the control plane:[/red] {start}")
        raise typer.Exit(1)
    verification_uri = str(start.get("verificationUri") or f"{cfg.base_url}/device")
    interval = max(1, int(start.get("intervalSeconds", 5)))
    expires_in = int(start.get("expiresInSeconds", 600))
    full_uri = f"{verification_uri}?code={user_code}"

    console.print(
        f"\nConfirm this code in your browser: [bold cyan]{user_code}[/bold cyan]"
    )
    console.print(f"  [cyan]{full_uri}[/cyan]")
    console.print(
        f"[dim]The code expires in {expires_in // 60} minutes. "
        "Waiting for approval…[/dim]\n"
    )
    try:
        webbrowser.open(full_uri)
    except Exception:
        pass  # headless / no browser — the printed URL is the fallback

    consecutive_errors = 0
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            resp = client.device_poll(device_code)
        except CloudError as e:
            consecutive_errors += 1
            if consecutive_errors >= 3:
                console.print(f"[red]Cloud unreachable while waiting:[/red] {e}")
                raise typer.Exit(1)
            continue
        consecutive_errors = 0

        status = str(resp.get("status", ""))
        if status == "pending":
            continue
        if status == "approved":
            cfg.email = resp.get("email") or cfg.email
            cfg.token = resp.get("accessToken")
            cfg.refresh_token = resp.get("refreshToken")
            if not cfg.token:
                console.print("[red]Approved, but no access token was returned.[/red]")
                raise typer.Exit(1)
            path = cloud_config.save(cfg)
            console.print(
                f"[green]Logged in[/green] as {cfg.email} → {cfg.base_url} "
                f"[dim]({path})[/dim]"
            )
            return
        # expired (or anything unrecognized): the record is gone server-side.
        console.print(
            "[red]The code expired before it was approved.[/red] "
            "Run [cyan]ortim cloud login[/cyan] again."
        )
        raise typer.Exit(1)

    console.print(
        "[red]Timed out waiting for approval.[/red] "
        "Run [cyan]ortim cloud login[/cyan] again."
    )
    raise typer.Exit(1)


@cloud_app.command()
def login(
    email: str = typer.Argument(
        None,
        help="Account email — only for the legacy password login. "
        "Omit to sign in via the browser (works for Google accounts).",
    ),
    password: str = typer.Option(
        None, "--password",
        help="Account password (legacy path; prompted if omitted while "
        "an email is given).",
    ),
) -> None:
    """Sign in to Ortim Cloud and store the access token.

    Default (no arguments): browser device-code flow — a short code is
    confirmed on cloud.ortim.dev/device. Works for Google sign-in
    accounts, which have no password. `ortim cloud login <email>` keeps
    the legacy email+password path.
    """
    cfg = cloud_config.load()
    client = CloudClient(cfg.base_url)

    if email is None:
        _device_login(client, cfg)
        return

    if password is None:
        password = typer.prompt("Password", hide_input=True)
    try:
        token = client.login(email, password)
    except CloudError as e:
        console.print(f"[red]Login failed:[/red] {e}")
        console.print(
            "[dim]Signed up with Google? Your account has no password — "
            "run [cyan]ortim cloud login[/cyan] (no email) to sign in via "
            "the browser.[/dim]"
        )
        raise typer.Exit(1)
    cfg.email = email
    cfg.token = token
    path = cloud_config.save(cfg)
    console.print(f"[green]Logged in[/green] as {email} → {cfg.base_url} [dim]({path})[/dim]")


@cloud_app.command()
def logout() -> None:
    """Clear the stored access token."""
    cfg = cloud_config.load()
    cfg.token = None
    cloud_config.save(cfg)
    console.print("[green]Logged out.[/green]")


@cloud_app.command()
def status() -> None:
    """Show cloud connection + login state."""
    cfg = cloud_config.load()
    console.print(f"endpoint : [cyan]{cfg.base_url}[/cyan]")
    console.print(f"account  : {cfg.email or '[dim]—[/dim]'}")
    console.print(
        "auth     : "
        + ("[green]logged in[/green]" if cfg.logged_in else "[yellow]logged out[/yellow]")
    )


@cloud_app.command()
def orgs() -> None:
    """List organizations you belong to."""
    client, _ = _client()
    try:
        result = client.list_orgs()
    except CloudError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    if not result:
        console.print("[dim]No organizations. Create one in the dashboard.[/dim]")
        return
    for o in result:
        console.print(
            f"[cyan]{o.get('id')}[/cyan]  {o.get('name')} "
            f"[dim]({o.get('myRole')}, seats {o.get('activeSeats')}/{o.get('seatLimit')})[/dim]"
        )


@cloud_app.command()
def link(
    org: str = typer.Option(..., "--org", help="Organization id"),
    name: str = typer.Option(None, "--name", help="Project name (default: workspace name)"),
    project: str = typer.Option(None, "--project", "-p", help="Workspace id (default: cwd)"),
) -> None:
    """Create/link the current workspace to a cloud org project."""
    proj, _store, location = _resolve_project(project)
    project_name = name or proj.name
    client, _ = _client()
    try:
        resp = client.link_project(org, project_name)
    except CloudError as e:
        console.print(f"[red]Link failed:[/red] {e}")
        raise typer.Exit(1)
    state = cloud_sync.LinkState(org_id=org, project_id=str(resp.get("id")), synced_seq=0)
    path = cloud_sync.save_link_state(location.metadata_dir, state)
    console.print(
        f"[green]Linked[/green] '{project_name}' → project {state.project_id} "
        f"[dim]({path})[/dim]"
    )


@cloud_app.command()
def sync(
    project: str = typer.Option(None, "--project", "-p", help="Workspace id (default: cwd)"),
) -> None:
    """Push redacted audit metadata + pipeline state to the cloud.

    Offline-safe: a cloud outage prints a warning and exits 0 without
    advancing the local cursor — the pipeline is never blocked.
    """
    proj, store, location = _resolve_project(project)
    link_state = cloud_sync.load_link_state(location.metadata_dir)
    if link_state is None:
        console.print(
            "[red]Project not linked.[/red] Run [cyan]ortim cloud link --org <id>[/cyan] first."
        )
        raise typer.Exit(1)

    state_obj = getattr(proj, "state", None)
    current_state = getattr(state_obj, "value", None) or (
        str(state_obj) if state_obj is not None else None
    )

    payload, new_cursor = cloud_sync.build_payload(
        store.audit_log_path(),
        after_seq=link_state.synced_seq,
        current_state=current_state,
    )

    if not payload["events"] and new_cursor == link_state.synced_seq:
        console.print("[dim]Nothing to sync (cursor up to date).[/dim]")
        return

    client, _ = _client()
    try:
        result = client.sync(link_state.project_id, payload)
    except CloudError as e:
        # Offline / server error: do NOT advance the cursor, do NOT fail.
        console.print(f"[yellow]Sync deferred (cloud unreachable):[/yellow] {e}")
        raise typer.Exit(0)

    link_state.synced_seq = new_cursor
    cloud_sync.save_link_state(location.metadata_dir, link_state)
    console.print(
        f"[green]Synced[/green] accepted={result.get('accepted')} "
        f"skipped={result.get('skipped')} head={str(result.get('headHash'))[:12]}…"
    )


@cloud_app.command()
def policy(
    org: str = typer.Option(None, "--org", help="Organization id (default: linked project's org)"),
    project: str = typer.Option(None, "--project", "-p", help="Workspace id (default: cwd)"),
) -> None:
    """Pull and display the org governance policy (CLI enforces it locally)."""
    org_id = org
    metadata_dir = None
    if org_id is None:
        _proj, _store, location = _resolve_project(project)
        metadata_dir = location.metadata_dir
        link_state = cloud_sync.load_link_state(metadata_dir)
        if link_state is None:
            console.print("[red]No --org and project not linked.[/red]")
            raise typer.Exit(1)
        org_id = link_state.org_id

    client, _ = _client()
    try:
        pol = client.get_policy(org_id)
    except CloudError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Cache for local run-time enforcement (execute / run-all read this).
    if metadata_dir is not None:
        try:
            cloud_policy.save_policy_cache(metadata_dir, org_id, pol)
        except OSError:
            pass

    gates = pol.get("mandatoryGates") or []
    providers = pol.get("allowedProviders") or []
    budget = pol.get("budgetCapUsd")
    console.print(f"mandatory gates  : {', '.join(gates) if gates else '[dim]none[/dim]'}")
    console.print(
        f"allowed providers: {', '.join(providers) if providers else '[dim]any[/dim]'}"
    )
    console.print(f"budget cap (USD) : {budget if budget is not None else '[dim]none[/dim]'}")


def register(app: typer.Typer) -> None:
    """Mount the `cloud` subcommand group onto the top-level app."""
    app.add_typer(cloud_app, name="cloud")
