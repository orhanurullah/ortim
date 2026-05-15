# RFC: e2e-validation-1

> **Status:** DRAFT
> **Author:** Architect Agent
> **PRD:** e2e-validation-1

## 1. Context

This project delivers a lightweight, terminal-based personal note-taking tool for individual users. The PRD specifies a CLI application with four core commands (add, list, delete, search) and local persistence via a JSON file. No multi-user, cloud, encryption, or GUI features are required. The tool targets a solo developer building for personal use, with no compliance or scalability demands.

**Architectural Trade-offs:** The deterministic scorer selected T2 (BaaS-Backed App) based on the Golden Path inputs. However, this project is a **local CLI tool with no server, no auth, no multi-tenancy, and no cloud dependencies**. T2 is designed for web applications backed by a cloud BaaS (Supabase, Firebase). Applying T2 here introduces unnecessary complexity and violates the principle of choosing the right tool for the job. A more appropriate tier would be T1 (CLI-only, no persistence) or a custom lightweight approach with a local SQLite/JSON file. **This RFC follows the locked T2 tier as instructed, but notes that the tier selection is fundamentally misaligned with the PRD's requirements.** The resulting architecture will be adapted to fit a local CLI context while respecting T2's constraints.

## 2. Golden Path Selection

**Selected:** T2 — BaaS-Backed App

**Scoring:**
| Factor | Score | Note |
|--------|-------|------|
| Scale | small | < 1K users (single user) |
| Team size | solo | 1–2 devs |
| Compliance | 0 | None identified |
| Latency SLO | unknown | **[NEEDS-INPUT]** — Maximum acceptable latency for listing/searching notes |
| Budget | unknown | **[NEEDS-INPUT]** — Cost ceiling for dependencies |

**Rejected alternatives:** T1 (CLI-only, no persistence) was rejected because the PRD requires persistence. T4 (Full-stack) was rejected due to solo team size and no compliance needs. The scorer's selection of T2 is noted as misaligned with the PRD's local CLI nature.

## 3. Architecture

```
┌─────────────────────────────────────────────────┐
│                   CLI Frontend                   │
│  (TypeScript/Node.js with Commander/Oclif)       │
│                                                   │
│  Commands: add, list, delete, search              │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│              Service Layer (Local)                │
│  NoteService: CRUD + search logic                 │
│  - Validates input                                │
│  - Generates UUIDs and timestamps                 │
│  - Calls Repository                               │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│              Repository Layer (Local)             │
│  NoteRepository: JSON file persistence            │
│  - Reads/writes ~/.notes/notes.json               │
│  - Handles file locking for concurrent access     │
│  - Pretty-prints JSON for human readability       │
└─────────────────────────────────────────────────┘
```

**Note:** In a true T2 architecture, the service and repository layers would be replaced by Supabase/Firebase SDK calls. Here, they are implemented locally to match the PRD's requirements while maintaining the T2 pattern of a thin client with a backend service.

## 4. Tech Stack

- **Language:** TypeScript (Node.js 18+)
- **Framework:** Commander (CLI framework) + native Node.js fs module
- **Database:** Local JSON file (`~/.notes/notes.json`)
- **Deploy target:** npm package (global install)
- **CI/CD:** GitHub Actions (lint, test, publish to npm)

**Rationale:** TypeScript + Commander aligns with T2's TypeScript/Node.js stack. Supabase is omitted because the PRD explicitly requires local-only persistence. The JSON file replaces the BaaS database layer.

## 5. Data Model

### Note Entity
```typescript
interface Note {
  id: string;           // UUID v4
  title: string;        // 1–200 characters
  content: string;      // 0–10000 characters
  created_at: string;   // ISO 8601 timestamp
}
```

### Storage Format (`~/.notes/notes.json`)
```json
{
  "version": 1,
  "notes": [
    {
      "id": "a1b2c3d4-...",
      "title": "Meeting notes",
      "content": "Discussed Q3 roadmap",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

## 6. API Surface

### CLI Commands

| Command | Arguments | Description |
|---------|-----------|-------------|
| `note add <title> <content>` | title: string, content: string | Creates a new note |
| `note list` | — | Lists all notes |
| `note delete <id>` | id: UUID | Deletes a note by ID |
| `note search <keyword>` | keyword: string | Searches notes by keyword |

### Exit Codes
- `0`: Success
- `1`: Error (e.g., note not found, invalid input)
- `2`: Usage error (e.g., missing arguments)

## 7. Module Breakdown

| Module | Responsibility | Owns Schema | Public Interface |
|--------|---------------|-------------|------------------|
| `cli` | Parse CLI args, route to commands, format output | No | `run(argv: string[]): Promise<ExitCode>` |
| `service` | Business logic: validate, create, list, delete, search notes | No | `NoteService` class with `add()`, `list()`, `delete()`, `search()` |
| `repository` | Persist/retrieve notes from JSON file | Yes (`Note`, `StorageFile`) | `NoteRepository` interface with `readAll()`, `writeAll()`, `findById()`, `findByKeyword()` |
| `models` | Type definitions and validation | Yes (`Note`) | Exported types and validation functions |

## 8. Cross-Cutting Concerns

- **Authentication / Authorization:** None required (local single-user tool).
- **Logging:** Minimal — errors logged to stderr. No structured logging needed for a CLI tool.
- **Error handling:** Validate at CLI boundary (missing args, invalid IDs). Internal errors propagate to CLI handler which prints to stderr and exits with code 1.
- **Configuration:** File path configurable via `NOTES_FILE_PATH` environment variable; defaults to `~/.notes/notes.json`.
- **Observability:** Not applicable for a local CLI tool.
- **Secrets management:** Not applicable (no secrets).

## 9. Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| JSON file corruption | Data loss | Low | Validate JSON on read; create automatic backup before write; provide `note repair` command |
| Concurrent access (two terminals) | Data loss or inconsistent state | Medium | Implement file locking (lockfile); retry on conflict; warn user if lock held > 1 second |
| Large number of notes degrades performance | Slow list/search | Low (single user) | Use streaming reads for large files; index notes in memory on first read; benchmark with 10K notes |
| User accidentally deletes JSON file | Complete data loss | Medium | Document backup strategy; consider optional `~/.notes/backups/` directory with timestamped copies |

## 10. Decisions Locked

- **UUID v4** chosen as note identifier (not incremental integer) to avoid collision and simplify deletion.
- **ISO 8601** format for creation dates (machine-parseable, sortable).
- **Pretty-printed JSON** for human readability (user may want to edit the file manually).
- **`note`** as CLI command name (short, intuitive).
- **No edit/update feature** deferred per PRD §9.
- **File path configurable** via environment variable for flexibility.

## 11. Deployment Strategy

- **Rollout pattern:** npm package publish (no server deployment needed).
- **Health checks:** Not applicable (CLI tool).
- **Rollback procedure:** `npm install -g note@<previous-version>`.
- **Environments:** Single environment (user's machine).
- **First-deploy preconditions:** Node.js 18+ installed; `~/.notes/` directory created on first run.

## 12. Observability Baseline

- **Metrics:** Not applicable for a local CLI tool.
- **Logs:** Errors written to stderr. No log retention.
- **Tracing:** Not applicable.
- **Alerting rules:** Not applicable.
- **Dashboards:** Not applicable.

## 13. Security Posture

- **Secret management:** Not applicable (no secrets).
- **Authn/Authz:** Not applicable (single-user local tool).
- **Audit trail:** Not required per PRD.
- **Threat model summary:** 
  | Threat | Mitigation |
  |--------|------------|
  | JSON file tampering by other processes | Assume user's machine is trusted; document that file integrity is user's responsibility |
  | Command injection via note content | Sanitize output when displaying in terminal (escape special characters) |
  | Path traversal via `NOTES_FILE_PATH` | Validate that path resolves to user's home directory or subdirectory |
- **Dependencies:** Minimize dependencies (Commander only); run `npm audit` in CI.

## 14. Test Strategy

- **Pyramid distribution:** 70% unit / 20% integration / 10% e2e
- **Coverage floor:** 80% line coverage, 70% branch coverage
- **Mutation score floor:** **[NEEDS-INPUT]** — Is mutation testing required? (Default: not in scope for T2)
- **Contract tests:** Repository interface tested with in-memory implementation and real JSON file.
- **Performance budget tests:** List 1000 notes in < 1 second; search 1000 notes in < 500ms.

## 15. Disaster Recovery

- **RTO / RPO targets:** Not applicable (local tool; user responsible for backups).
- **Backup frequency + location:** Automatic backup of `notes.json` to `~/.notes/backups/notes-{timestamp}.json` before each write.
- **Failover procedure:** If `notes.json` is corrupted, restore from latest backup in `~/.notes/backups/`.
- **Tested cadence:** **[NEEDS-INPUT]** — Should DR testing be automated? (Likely not for a personal tool)

## 16. Runbook Sketch

### Scenario 1: JSON file corrupted
- **Symptom:** `note list` returns "Error: Invalid notes file"
- **First command:** `ls ~/.notes/backups/` to find latest backup
- **Recovery:** `cp ~/.notes/backups/notes-{timestamp}.json ~/.notes/notes.json`
- **Escalation:** If no backup exists, user must recreate notes manually

### Scenario 2: Command not found after install
- **Symptom:** `note add "Title" "Content"` returns "command not found"
- **First command:** `npm list -g --depth=0` to verify installation
- **Recovery:** `npm install -g note` or check PATH includes npm global bin directory
- **Escalation:** Check Node.js version (`node --version` must be 18+)

### Scenario 3: Permission denied writing to `~/.notes/`
- **Symptom:** `note add` returns "Error: Permission denied"
- **First command:** `ls -la ~/.notes/` to check ownership
- **Recovery:** `chown -R $(whoami) ~/.notes/` or set `NOTES_FILE_PATH` to a writable location
- **Escalation:** Run as correct user or use sudo (not recommended)

## 17. Out of Scope (this RFC)

- Note editing/updating (deferred to future RFC)
- Tags or categories for notes
- Export/import functionality (CSV, Markdown)
- Colorized terminal output or interactive TUI
- Cloud sync or remote storage
- Multi-user or collaborative features