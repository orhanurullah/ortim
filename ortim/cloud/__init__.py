# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""Ortim Cloud client — Observer layer (CLI → Core Platform).

The CLI runs locally; it pushes only REDACTED audit metadata + pipeline
state to the cloud and pulls the org governance policy. Source code is
never sent. The control plane is the existing Spring platform (app #2 = ortim).
"""

from ortim.cloud.client import CloudClient, CloudError
from ortim.cloud.config import CloudConfig

__all__ = ["CloudClient", "CloudError", "CloudConfig"]
