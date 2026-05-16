# Local LLM providers (Ollama, LM Studio)

Ortim supports running any agent role against a local OpenAI-compatible LLM server. The most-tested path is **Ollama** (`localhost:11434`). LM Studio and llama.cpp's built-in server work via the same shape.

This unlocks two use cases:

1. **Cost-free development** — iterate on prompts, retry-loop, and integration tests against a local model that costs nothing per call.
2. **KVKK / data-residency compliance** — when a customer's brief contains regulated PII, route Babel and Worker locally so prompts never leave the machine.

The system is **explicitly not** marketed as "fully local" today. Critical roles (Architect, SecurityReviewer) still default to cloud; their quality gap on small local models is too wide. This guide documents the **hybrid** pattern that actually works.

---

## Setup

```bash
# 1. Install Ollama (https://ollama.com)
# 2. Pull a coder-tuned model
ollama pull qwen2.5-coder:7b      # ~4.7 GB, runs on 16 GB RAM
ollama pull qwen2.5-coder:14b     # ~9 GB, runs on 24 GB RAM
ollama pull deepseek-coder-v2:16b # ~9 GB, MoE — faster inference

# 3. Verify
ollama list
curl http://localhost:11434/v1/models
```

Ortim talks to the OpenAI-compatible endpoint, not Ollama's native one. The endpoint is `http://localhost:11434/v1` by default. Override with `OLLAMA_BASE_URL` if you run Ollama on another host:

```bash
export OLLAMA_BASE_URL=http://gpu-box.local:11434/v1
```

No API key is required.

---

## Quality tier — what local LLMs do well, badly, and not at all

A 7B-14B local model is a **junior coder with no project memory**. Match the role to that mental model.

| Role | Local 7B-14B (Qwen / DeepSeek-Coder) | Local 30B+ (Qwen-32B, Codestral) | Notes |
|---|---|---|---|
| **Babel** (TR↔EN translation, intent extraction) | ✅ good | ✅ excellent | Translation is well-trained at every size. Safe to route local. |
| **IntentAnalyst** (extract goals from a brief) | 🟡 acceptable | ✅ good | Schema adherence weaker at 7B — set `temperature=0`. |
| **Worker** (write the code for a single task) | 🟡 acceptable for T0-T2 | ✅ good for T0-T3 | Skills + acceptance criteria carry most of the work. Watch for hallucinated imports. |
| **Reviewer** (verdict + acceptance check) | 🟡 acceptable | 🟡 acceptable | Rubric format (Item 21) helps. Length validator catches drop cases. |
| **Architect** | ❌ poor | 🟡 risky | Wrong tier choice / phantom libraries (Item 40 class). Keep on cloud. |
| **SecurityReviewer** | ❌ poor | ❌ poor | Misses CVE patterns local models weren't trained on recent enough. Always cloud. |
| **Orchestrator** | ❌ poor | 🟡 risky | DAG validation depends on hard rules that LLMs follow inconsistently. Keep on cloud. |

✅ excellent · ✅ good · 🟡 acceptable · ❌ poor

---

## Model size — what fits on what

| RAM | Recommended model | Throughput | Suggested roles |
|---|---|---|---|
| 8 GB | `qwen2.5-coder:1.5b` | ~30 tok/s | Babel only (translation) |
| 16 GB | `qwen2.5-coder:7b` | ~25 tok/s | Babel, IntentAnalyst |
| 24 GB | `qwen2.5-coder:14b`, `deepseek-coder-v2:16b` (MoE) | ~30 tok/s (MoE) | Babel, IntentAnalyst, Worker |
| 32-48 GB | `qwen2.5-coder:32b` (quantized) | ~15 tok/s | + Reviewer |
| 64 GB+ / dual-GPU | `codestral:22b`, `qwen2.5-coder:72b` | varies | + experimental Architect |

GPU offload (CUDA, Metal) roughly doubles throughput; tokens-per-second varies wildly with quantization (Q4_K_M is the safe default for code).

---

## Routing patterns

Routing is per-role via env vars. The router (`runtime/llm/router.py`) reads `<ROLE>_PROVIDER` and `<ROLE>_MODEL` and falls back to `LLM_PROVIDER` / `DEFAULT_MODEL` for unset roles.

### Pattern A — Pure local (development, low-stakes)

```bash
LLM_PROVIDER=ollama
DEFAULT_MODEL=qwen2.5-coder:7b
```

Every role hits Ollama. Acceptable for hello-world projects and prompt iteration. **Do not use in production** — Architect and SecurityReviewer will misbehave on real briefs.

### Pattern B — Hybrid (KVKK-aware default)

```bash
LLM_PROVIDER=anthropic                  # critical default

BABEL_PROVIDER=ollama                   # translation — local
BABEL_MODEL=qwen2.5-coder:7b

WORKER_PROVIDER=deepseek                # cheap remote
REVIEWER_PROVIDER=deepseek

# ARCHITECT_PROVIDER unset → falls back to anthropic
# SECURITY_REVIEWER_PROVIDER unset → falls back to anthropic
```

Babel runs local so user briefs (possibly carrying PII or trade secrets in TR) never leave the machine. Worker + Reviewer run on DeepSeek (cheap, high volume). Architect + SecurityReviewer stay on Claude — they make the expensive decisions that can't be undone cheaply.

### Pattern C — Air-gapped (compliance, demo)

```bash
LLM_PROVIDER=ollama
DEFAULT_MODEL=qwen2.5-coder:14b

ARCHITECT_MODEL=qwen2.5-coder:32b       # bigger model for decisions
SECURITY_REVIEWER_MODEL=qwen2.5-coder:32b
```

Everything stays on the box. Expect lower quality and longer iteration time. Useful for regulated demos where "no network egress" is the audit answer that matters most.

---

## Cost accounting

Local providers price input and output at **$0.00 per 1M tokens** in the budget gate (G7). The audit log still records token counts so you can observe utilization and right-size the model. The "real" cost — electricity, hardware amortization, your time — does not enter the ledger.

If you mix local and remote in one run, the budget gate enforces the remote-provider limits as usual; local calls don't deplete the budget.

---

## Known limits

- **No streaming.** The current client is one-shot request/response. Local models with long completions feel slower than the same wall-time on a streaming UI.
- **No tool use.** OpenAI-compatible function-calling support varies wildly across Ollama models. Ortim does not depend on tool calls today, so this is a future-features gap, not a regression.
- **Token counts may be 0.** Some Ollama versions omit the `usage` field on non-streaming responses. The audit log records 0 in that case; budget gate is unaffected (pricing is 0).
- **Schema adherence varies.** Smaller models drift more from structured JSON output. If you see `pydantic.ValidationError` from the Reviewer or Architect on a local model, try the next size up before debugging the prompt.

---

## Quick test

After setup, the smallest end-to-end check that the local path works:

```bash
LLM_PROVIDER=ollama \
DEFAULT_MODEL=qwen2.5-coder:7b \
ortim doctor
```

`ortim doctor` makes a minimal LLM call to verify the configured provider is reachable. A green check on this line means the wiring is good; routing per role is then a matter of env vars only.
