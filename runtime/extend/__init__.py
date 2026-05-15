# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2026 ortim.dev
"""M3.1 — `ortim extend`: iterative dev on shipped projects.

After a project hits DONE, `ortim extend <id> "<feature brief>"` enters
a delta cycle that produces a delta PRD section, delta RFC section, and
new tasks appended to the existing DAG. LockedStack is unchanged; existing
DONE tasks stay DONE; new tasks reference existing exports via M4's
cross-task export visibility.

Public API:
    ExtensionIntent   — structured delta brief (per-cycle)
    DagDelta          — new tasks appended in one extend cycle
"""

from runtime.extend.delta_writer import (
    DeltaSectionMalformed,
    append_delta_section,
    section_cycles_in,
)
from runtime.extend.drift import (
    DriftFinding,
    DriftReport,
    inspect_drift,
    to_json_dict as drift_to_json_dict,
)
from runtime.extend.extender_agent import (
    BLOCKED_STACK_MARKER,
    ExtenderAgent,
)
from runtime.extend.schema import DagDelta, ExtensionIntent

__all__ = [
    "BLOCKED_STACK_MARKER",
    "DagDelta",
    "DeltaSectionMalformed",
    "DriftFinding",
    "DriftReport",
    "ExtenderAgent",
    "ExtensionIntent",
    "append_delta_section",
    "drift_to_json_dict",
    "inspect_drift",
    "section_cycles_in",
]
