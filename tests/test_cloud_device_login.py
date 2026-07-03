# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for `ortim cloud login` device-code flow (RFC 8628 simplified).

Why this exists: most platform accounts are Google sign-in and have NO
password — the legacy email+password login locks them out of the CLI.
The default login is now the browser device flow; these tests pin:

  * no-args login runs start → poll → stores token/refresh/email
  * pending → approved polling loop (no premature exit)
  * expired / timeout → clear error, exit 1
  * `ortim cloud login <email>` keeps the legacy password path
  * transient poll errors tolerated; persistent ones abort
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from ortim.cloud import config as cloud_config  # noqa: E402
from ortim.cloud.client import CloudClient, CloudError  # noqa: E402
from ortim.main import app  # noqa: E402

START_RESPONSE = {
    "deviceCode": "dc-secret",
    "userCode": "BCDF-GHJK",
    "verificationUri": "https://cloud.ortim.dev/device",
    "expiresInSeconds": 600,
    "intervalSeconds": 5,
}

APPROVED_RESPONSE = {
    "status": "approved",
    "email": "google-only@example.com",
    "accessToken": "at-123",
    "refreshToken": "rt-456",
    "tokenType": "Bearer",
}


@pytest.fixture()
def cloud_cfg_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cloud.toml"
    monkeypatch.setenv("ORTIM_CLOUD_CONFIG", str(path))
    return path


@pytest.fixture(autouse=True)
def _fast_and_headless(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setattr("webbrowser.open", lambda _u: True)


def test_login_no_args_runs_device_flow_and_stores_tokens(
    cloud_cfg_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    polls: list[str] = []

    def fake_poll(self: CloudClient, device_code: str) -> dict:
        polls.append(device_code)
        # First two polls pending, then approved — exercises the loop.
        if len(polls) < 3:
            return {"status": "pending"}
        return APPROVED_RESPONSE

    monkeypatch.setattr(CloudClient, "device_start", lambda self: START_RESPONSE)
    monkeypatch.setattr(CloudClient, "device_poll", fake_poll)

    result = CliRunner().invoke(app, ["cloud", "login"], catch_exceptions=False)

    assert result.exit_code == 0, result.stdout
    assert "BCDF-GHJK" in result.stdout
    assert "Logged in" in result.stdout
    assert polls == ["dc-secret"] * 3

    cfg = cloud_config.load()
    assert cfg.token == "at-123"
    assert cfg.refresh_token == "rt-456"
    assert cfg.email == "google-only@example.com"


def test_login_device_flow_expired_is_clear_error(
    cloud_cfg_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(CloudClient, "device_start", lambda self: START_RESPONSE)
    monkeypatch.setattr(
        CloudClient, "device_poll", lambda self, dc: {"status": "expired"}
    )

    result = CliRunner().invoke(app, ["cloud", "login"], catch_exceptions=False)

    assert result.exit_code == 1
    assert "expired" in result.stdout
    assert cloud_config.load().token is None


def test_login_device_flow_tolerates_transient_poll_errors(
    cloud_cfg_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def flaky_poll(self: CloudClient, device_code: str) -> dict:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise CloudError("blip")
        return APPROVED_RESPONSE

    monkeypatch.setattr(CloudClient, "device_start", lambda self: START_RESPONSE)
    monkeypatch.setattr(CloudClient, "device_poll", flaky_poll)

    result = CliRunner().invoke(app, ["cloud", "login"], catch_exceptions=False)

    assert result.exit_code == 0, result.stdout
    assert cloud_config.load().token == "at-123"


def test_login_device_flow_aborts_after_persistent_poll_errors(
    cloud_cfg_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(CloudClient, "device_start", lambda self: START_RESPONSE)

    def always_fails(self: CloudClient, device_code: str) -> dict:
        raise CloudError("cloud down")

    monkeypatch.setattr(CloudClient, "device_poll", always_fails)

    result = CliRunner().invoke(app, ["cloud", "login"], catch_exceptions=False)

    assert result.exit_code == 1
    assert "unreachable" in result.stdout


def test_login_with_email_uses_legacy_password_path(
    cloud_cfg_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, str] = {}

    def fake_login(self: CloudClient, email: str, password: str) -> str:
        seen["email"] = email
        seen["password"] = password
        return "legacy-token"

    monkeypatch.setattr(CloudClient, "login", fake_login)
    monkeypatch.setattr(
        CloudClient,
        "device_start",
        lambda self: (_ for _ in ()).throw(AssertionError("device flow must not run")),
    )

    result = CliRunner().invoke(
        app,
        ["cloud", "login", "dev@example.com", "--password", "hunter2"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.stdout
    assert seen == {"email": "dev@example.com", "password": "hunter2"}
    assert cloud_config.load().token == "legacy-token"


def test_legacy_login_failure_points_google_users_to_device_flow(
    cloud_cfg_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_login(self: CloudClient, email: str, password: str) -> str:
        raise CloudError("401 Unauthorized")

    monkeypatch.setattr(CloudClient, "login", fail_login)

    result = CliRunner().invoke(
        app,
        ["cloud", "login", "dev@example.com", "--password", "wrong"],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "Google" in result.stdout  # the device-flow hint
