# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Stdlib HTTP client for the Ortim Cloud control plane.

No `requests` dependency — `urllib.request` only, matching the project's
stdlib-first posture. Auth uses the platform JWT as `Authorization: Bearer`;
the token is extracted from the `access_token` Set-Cookie on login.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class CloudError(Exception):
    """Network failure or non-2xx response from the control plane."""


def _extract_cookie(headers: Any, name: str) -> str | None:
    """Pull a cookie value from response Set-Cookie headers."""
    try:
        cookies = headers.get_all("Set-Cookie") or []
    except AttributeError:
        raw = headers.get("Set-Cookie")
        cookies = [raw] if raw else []
    prefix = name + "="
    for c in cookies:
        for part in c.split(";"):
            part = part.strip()
            if part.startswith(prefix):
                value = part[len(prefix):]
                return value or None
    return None


class CloudClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(
        self, method: str, path: str, body: dict | None = None, auth: bool = True
    ) -> tuple[Any, Any]:
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        if auth and self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                payload = json.loads(raw) if raw.strip() else {}
                return payload, resp.headers
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise CloudError(f"{e.code} {e.reason}: {detail[:500]}") from e
        except urllib.error.URLError as e:
            raise CloudError(f"cannot reach {url}: {e.reason}") from e

    # ---- auth ----

    def login(self, email: str, password: str) -> str:
        _, headers = self._request(
            "POST", "/api/auth/login", {"email": email, "password": password}, auth=False
        )
        token = _extract_cookie(headers, "access_token")
        if not token:
            raise CloudError("login succeeded but no access_token cookie was returned")
        self.token = token
        return token

    # ---- orgs / projects / policy / sync ----

    def list_orgs(self) -> list[dict]:
        data, _ = self._request("GET", "/api/ortim/orgs")
        return data if isinstance(data, list) else []

    def create_org(self, name: str) -> dict:
        data, _ = self._request("POST", "/api/ortim/orgs", {"name": name})
        return data

    def link_project(self, org_id: str, name: str) -> dict:
        data, _ = self._request(
            "POST", f"/api/ortim/orgs/{org_id}/projects", {"name": name}
        )
        return data

    def sync(self, project_id: str, payload: dict) -> dict:
        data, _ = self._request("POST", f"/api/ortim/projects/{project_id}/sync", payload)
        return data

    def get_policy(self, org_id: str) -> dict:
        data, _ = self._request("GET", f"/api/ortim/orgs/{org_id}/policy")
        return data
