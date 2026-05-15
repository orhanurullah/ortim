# E2E Fixtures — Captured Real-LLM Baselines

Each subdirectory here is a frozen snapshot of a real workspace at a
significant point in time. The tests in `tests/e2e/test_baselines.py`
read these artifacts and assert structural + content invariants.

These are **regression armor**, not source of truth. The audit log + the
running workspaces are authoritative; these are sampled copies kept
under version control so a code change that quietly alters the planning
chain's output shape fails loudly.

## Current baselines

| Fixture | Operational path | Why it's here |
|---|---|---|
| `proofpoint48` | M3.1 v1 extend cycle, T4/web TS+React | Post-Item-48 aggregated delta (4 tasks for 11 ACs). 8/9 DONE + T-009 AWAITING_HITL. The "happy path + valid HITL" reference. |
| `b8d60b6f5791` | Pre-M2 greenfield CLI (no stack.json) | 6/6 DONE; classic 4-module layout (cli/models/repository/service). Backward-compat anchor for the universal task_dag schema. |
| `1b9c9f9ca18b` | Pre-Item-48 extend (10-task drift) | Historical — the same brief as proofpoint48 but produced 10 delta tasks before Item 48. Schema-compat only; the over-granularization is NOT a correctness target. |

## How tests use these

- **Universal** (parametrized): file presence, Pydantic-model parse-ability, task-ID format.
- **Per-fixture**: locked-stack contents (proofpoint48), HITL state (proofpoint48 T-009), module layout (cli_greenfield), schema-compat + historical drift signature (pre_item48_extend).

## How to add a new baseline

1. Run a real-LLM workspace to the state you want to capture.
2. `python scripts/record_e2e_fixture.py <workspace-id> [<fixture-name>]`
3. Add a per-fixture pytest function in `tests/e2e/test_baselines.py`.
4. Update this README's table.

## How to re-record after an intentional behavior change

When a fix intentionally changes one of these baselines (e.g. a future
Item 48 refinement drops delta count from 4 to 3), re-record:

```powershell
python scripts/record_e2e_fixture.py proofpoint48
```

…then update the assertions in `test_baselines.py` to match the new
expected shape. Commit the fixture + the test diff together so the
"why this changed" is preserved in git history.

## Running the e2e tests

```powershell
pytest -m e2e -v
```

The fast suite default-excludes them via `addopts = ["-m", "not e2e"]`
in `pyproject.toml`.
