# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Tests for `ortim cloud share-audit` (shareable read-only audit link, P5).

Why this exists: the share link is the free→paid proof bridge — an agency
hands a client a URL instead of a promise. These tests pin:

  * happy path: linked project → POST with project id → URL printed once
  * --expires-in-days is forwarded; omitted means server default
  * unlinked project → clear error, exit 1
  * never-synced project → warning, but the link is still created
  * cloud error → clear error, exit 1
  * response without url → treated as an error
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from ortim.cloud import config as cloud_config  # noqa: E402
from ortim.cloud import sync as cloud_sync  # noqa: E402
from ortim.cloud.client import CloudClient, CloudError  # noqa: E402
from ortim.main import app  # noqa: E402

SHARE_RESPONSE = {
    "id": "9c1a2b3c-0000-0000-0000-000000000000",
    "url": "https://ortim.dev/ortim/audit/tok-raw-abc123",
    "expiresAt": "2026-08-02T10:00:00",
    "active": True,
}


@pytest.fixture()
def logged_in_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cloud.toml"
    monkeypatch.setenv("ORTIM_CLOUD_CONFIG", str(path))
    cfg = cloud_config.load()
    cfg.email = "member@example.com"
    cfg.token = "jwt-token"
    cloud_config.save(cfg)
    return path


class _FakeLocation:
    def __init__(self, metadata_dir: Path) -> None:
        self.metadata_dir = metadata_dir


def _link_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, synced_seq: int = 7
) -> None:
    """Fake a linked (and by default synced) workspace."""
    metadata_dir = tmp_path / "meta"
    metadata_dir.mkdir(exist_ok=True)
    cloud_sync.save_link_state(
        metadata_dir,
        cloud_sync.LinkState(org_id="org-1", project_id="proj-42", synced_seq=synced_seq),
    )
    monkeypatch.setattr(
        "ortim.cli.cloud._resolve_project",
        lambda _p: (object(), object(), _FakeLocation(metadata_dir)),
    )


def test_share_audit_prints_url_once(
    logged_in_cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, int | None]] = []

    def fake_share(self: CloudClient, project_id: str, expires_in_days: int | None = None) -> dict:
        calls.append((project_id, expires_in_days))
        return SHARE_RESPONSE

    _link_project(monkeypatch, tmp_path)
    monkeypatch.setattr(CloudClient, "share_audit", fake_share)

    result = CliRunner().invoke(app, ["cloud", "share-audit"], catch_exceptions=False)

    assert result.exit_code == 0, result.stdout
    assert calls == [("proj-42", None)]
    assert "https://ortim.dev/ortim/audit/tok-raw-abc123" in result.stdout
    assert "only once" in result.stdout  # tek-gösterim uyarısı

def test_share_audit_forwards_expiry_days(
    logged_in_cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, int | None]] = []

    def fake_share(self: CloudClient, project_id: str, expires_in_days: int | None = None) -> dict:
        calls.append((project_id, expires_in_days))
        return SHARE_RESPONSE

    _link_project(monkeypatch, tmp_path)
    monkeypatch.setattr(CloudClient, "share_audit", fake_share)

    result = CliRunner().invoke(
        app, ["cloud", "share-audit", "--expires-in-days", "7"], catch_exceptions=False
    )

    assert result.exit_code == 0, result.stdout
    assert calls == [("proj-42", 7)]


def test_share_audit_requires_linked_project(
    logged_in_cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata_dir = tmp_path / "meta-unlinked"
    metadata_dir.mkdir()
    monkeypatch.setattr(
        "ortim.cli.cloud._resolve_project",
        lambda _p: (object(), object(), _FakeLocation(metadata_dir)),
    )

    result = CliRunner().invoke(app, ["cloud", "share-audit"])

    assert result.exit_code == 1
    assert "not linked" in result.stdout.lower()


def test_share_audit_warns_when_nothing_synced_but_still_creates(
    logged_in_cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _link_project(monkeypatch, tmp_path, synced_seq=0)
    monkeypatch.setattr(
        CloudClient, "share_audit", lambda self, p, e=None: SHARE_RESPONSE
    )

    result = CliRunner().invoke(app, ["cloud", "share-audit"], catch_exceptions=False)

    assert result.exit_code == 0, result.stdout
    assert "Nothing synced yet" in result.stdout
    assert "tok-raw-abc123" in result.stdout


def test_share_audit_cloud_error_is_clear_and_exits_1(
    logged_in_cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_share(self: CloudClient, project_id: str, expires_in_days: int | None = None) -> dict:
        raise CloudError("503 Service Unavailable")

    _link_project(monkeypatch, tmp_path)
    monkeypatch.setattr(CloudClient, "share_audit", fake_share)

    result = CliRunner().invoke(app, ["cloud", "share-audit"])

    assert result.exit_code == 1
    assert "Could not create the share link" in result.stdout


def test_share_audit_response_without_url_is_an_error(
    logged_in_cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _link_project(monkeypatch, tmp_path)
    monkeypatch.setattr(CloudClient, "share_audit", lambda self, p, e=None: {"id": "x"})

    result = CliRunner().invoke(app, ["cloud", "share-audit"])

    assert result.exit_code == 1
    assert "Unexpected response" in result.stdout


def test_client_share_audit_posts_expected_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """CloudClient.share_audit hits the documented endpoint with the right body."""
    captured: dict = {}

    def fake_request(self: CloudClient, method: str, path: str, body=None, auth=True):
        captured.update(method=method, path=path, body=body, auth=auth)
        return SHARE_RESPONSE, {}

    monkeypatch.setattr(CloudClient, "_request", fake_request)
    client = CloudClient("https://cloud.ortim.dev", token="t")

    resp = client.share_audit("proj-42", 14)

    assert resp["url"].startswith("https://ortim.dev/ortim/audit/")
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/ortim/projects/proj-42/audit/share"
    assert captured["body"] == {"expiresInDays": 14}
    assert captured["auth"] is True

    client.share_audit("proj-42")
    assert captured["body"] == {}  # gün verilmezse sunucu varsayılanı (30)
