# RFC: web-todo-proofpoint-v3

> **Status:** DRAFT
> **Author:** Architect Agent
> **PRD:** web-todo-proofpoint-v3

## 1. Context

This project implements a single-user, browser-only task management application. All data persists via `localStorage` — no server, no authentication, no multi-user support. The application must load interactively within 3 seconds on modern broadband and pass all acceptance criteria defined in the PRD.

**Architectural Trade-offs:**
- The locked stack (React + Vite + sql.js) includes sql.js, which is a SQLite WebAssembly binding. For a `localStorage`-only persistence requirement, sql.js adds unnecessary complexity and bundle size. A simpler `localStorage` wrapper (e.g., a thin repository over `JSON.parse`/`JSON.stringify`) would satisfy the same requirement with zero dependencies. However, the stack is locked per the STACK_DIALOG negotiation. If sql.js is genuinely required for future-proofing (e.g., eventual sync to a server-side SQLite), this is acceptable; otherwise, `**[NEEDS-INPUT]**: Is sql.js required, or can we use a plain localStorage adapter? This would reduce bundle size and remove a WebAssembly dependency.`

## 2. Golden Path Selection

**Selected:** T4 — Modular Monolith

**Scoring:**
| Factor | Score | Note |
|--------|-------|------|
| Scale | small | Single user, no server |
| Team size | solo | Single developer |
| Compliance | 0 | None required |
| Latency SLO | low | 3s load time, no real-time |
| Budget | 0 | Open-source, no paid services |

**Rejected alternatives:** T0 (static content — not applicable, app has state), T1 (no backend — fits, but T4 is the default tier and the locked stack is T4-aligned), T5 (microservices — massive overkill for a single-user browser app).

## 3. Architecture

```
┌─────────────────────────────────────────────┐
│                  Browser                     │
│  ┌───────────────────────────────────────┐  │
│  │         React Application             │  │
│  │  ┌──────────┐  ┌──────────────────┐  │  │
│  │  │  UI       │  │  Task Module     │  │  │
│  │  │  Layer    │──│  (api/domain/    │  │  │
│  │  │ (Vite)   │  │   infra/http)    │  │  │
│  │  └──────────┘  └────────┬─────────┘  │  │
│  │                          │            │  │
│  │                    ┌─────▼──────┐     │  │
│  │                    │ sql.js DB  │     │  │
│  │                    │ (SQLite)   │     │  │
│  │                    └────────────┘     │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

The application is a single-page React app. The Task Module owns all business logic and persistence. The UI layer renders components and dispatches user actions to the module's public API. The module persists data to a SQLite database via sql.js, which stores its data in `localStorage` for cross-session persistence.

## 4. Tech Stack

- **Language:** TypeScript
- **Primary framework:** React + Vite
- **Package manager:** npm
- **Test command:** `npx vitest run`
- **Run command:** `npm run dev`
- **Key libraries:** sql.js, zod, uuid
- **Deploy target:** (unspecified) — `**[NEEDS-INPUT]**: Where should the built static assets be deployed? Options: GitHub Pages, Netlify, Vercel, or a simple static file server.`

## 5. Data Model

### Task Entity
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT (UUID) | PRIMARY KEY, NOT NULL | Generated via `uuid` library |
| title | TEXT | NOT NULL, max 500 chars | User-provided task description |
| completed | INTEGER (boolean) | NOT NULL, DEFAULT 0 | 0 = active, 1 = completed |
| created_at | TEXT (ISO 8601) | NOT NULL | Set on creation |
| updated_at | TEXT (ISO 8601) | NOT NULL | Updated on any modification |

**Schema SQL:**
```sql
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY NOT NULL,
    title TEXT NOT NULL CHECK(length(title) <= 500),
    completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

**Validation (zod):**
```typescript
const TaskSchema = z.object({
  id: z.string().uuid(),
  title: z.string().min(1).max(500),
  completed: z.boolean(),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
});
```

## 6. API Surface

The Task Module exposes a typed public API (no HTTP — in-process calls):

```typescript
// api/task.api.ts
interface ITaskAPI {
  createTask(title: string): Promise<Task>;
  getAllTasks(): Promise<Task[]>;
  completeTask(id: string): Promise<Task>;
  deleteTask(id: string): Promise<void>;
}
```

**Request/Response shapes:**
- `createTask(title: string)` → `Task` (id generated server-side in sql.js)
- `getAllTasks()` → `Task[]` (ordered by `created_at` ascending)
- `completeTask(id: string)` → `Task` (toggles `completed` boolean)
- `deleteTask(id: string)` → `void`

## 7. Module Breakdown

| Module | Responsibility | Owns Schema | Public Interface |
|--------|---------------|-------------|------------------|
| task | CRUD operations for tasks, persistence via sql.js | `tasks` table | `ITaskAPI` (create, getAll, complete, delete) |
| ui | React components, state management, rendering | None | Component props and event handlers |

**Note:** The `ui` module is not a separate directory in the traditional sense — it's the React app layer. The `task` module is the only domain module.

## 8. Cross-Cutting Concerns

- **Authentication / Authorization:** Not applicable — single-user, no auth.
- **Logging:** Console-based logging for development. No production logging needed (no server). Use `console.warn` for recoverable errors, `console.error` for unrecoverable.
- **Error handling:** Boundary errors at the UI layer catch and display a user-friendly message (e.g., "Something went wrong. Please refresh the page."). Internal module calls trust types and contracts. No silent catches.
- **Configuration:** No runtime configuration. Build-time env vars via Vite (`VITE_*`). `**[NEEDS-INPUT]**: Are there any build-time configuration values needed (e.g., app title, default locale)?`
- **Observability:** Not applicable for a client-only app. No metrics, tracing, or alerting.
- **Secrets management:** Not applicable — no secrets.

## 9. Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| `localStorage` quota exceeded (typically 5–10 MB) | User loses ability to save new tasks | Low (text-only tasks are tiny) | Validate task count before insert; warn user at 1000 tasks. sql.js stores entire DB in a single `localStorage` key — monitor size. |
| sql.js WebAssembly fails to load on older browsers | Application fails to initialize | Low (modern evergreen only) | Add a try-catch around sql.js initialization; show a fallback message if WebAssembly is unsupported. |
| User clears browser data (cookies/site data) | All tasks lost | Medium | Document in-app that data is stored locally and clearing browser data will delete tasks. No mitigation beyond documentation. |

## 10. Decisions Locked

- **Persistence via sql.js + localStorage:** The locked stack mandates sql.js. The DB file is persisted to `localStorage` under a known key (e.g., `web-todo-proofpoint-v3-db`).
- **Single module (task):** No identity, billing, or notifications modules are needed.
- **No routing:** Single-page, no React Router needed.
- **No state management library:** React's `useState`/`useReducer` is sufficient for a single-user task list.

## 11. Deployment Strategy

- **Rollout pattern:** Recreate (static site — swap old build with new build). No blue-green or canary needed for a static SPA.
- **Health checks:** Not applicable (no server). The app loads in the browser; if it fails, the user sees a blank page or error message.
- **Rollback procedure:** Revert the deployment to the previous build artifact. Time-to-recovery: < 5 minutes.
- **Environments:** Single production environment. `**[NEEDS-INPUT]**: Is a staging/development environment needed for previewing changes before production deployment?`
- **First-deploy preconditions:** `**[NEEDS-INPUT]**: What is the deploy target? (e.g., GitHub Pages, Netlify, Vercel). Preconditions depend on the target — e.g., for GitHub Pages: repository configured, `gh-pages` branch or `docs/` folder.`

## 12. Observability Baseline

- **Metrics (RED for services, USE for resources):** Not applicable — no server, no service mesh.
- **Logs:** Console-based. Required fields: `timestamp`, `event`, `data` (task ID, title). Destination: browser console. Retention: session-only.
- **Tracing:** Not applicable.
- **Alerting rules:** Not applicable.
- **Dashboards:** Not applicable.

## 13. Security Posture

- **Secret management:** Not applicable — no secrets.
- **Authn/Authz:** Not applicable — single-user, no auth.
- **Audit trail:** Not applicable — no audit requirements.
- **Threat model summary:**
  1. **XSS via task title:** If a user pastes malicious HTML/JS into the task title and the app renders it unsafely, it could execute in the user's own browser. **Mitigation:** Use React's default JSX escaping (no `dangerouslySetInnerHTML`). Validate title length and character set via zod.
  2. **localStorage tampering via browser dev tools:** A user can manually edit the sql.js DB in `localStorage`. **Mitigation:** This is the user's own data — no mitigation needed. Treat as user-intentional.
  3. **Dependency supply chain:** A compromised npm package could inject malicious code. **Mitigation:** Run `npm audit` in CI. Pin exact versions in `package-lock.json`.
- **Dependencies:** SAST via `npm audit` on every PR. Critical CVE policy: block merge until patched.

## 14. Test Strategy

- **Pyramid distribution:** 70% unit / 20% integration / 10% e2e (component tests with Vitest + jsdom).
- **Coverage floor:** 80% line coverage, 70% branch coverage.
- **Mutation score floor:** Not applicable (mutation testing not in scope for this project size).
- **Contract tests:** The `ITaskAPI` interface is tested via integration tests against a real sql.js in-memory database.
- **Performance budget tests:** Load time < 3 seconds on modern broadband. Measured via Lighthouse in CI (if deploy target supports it). `**[NEEDS-INPUT]**: Should we add a Lighthouse CI check to the pipeline?`

## 15. Disaster Recovery

- **RTO / RPO targets:** Not applicable — no server, no data loss beyond what the user clears in their browser.
- **Backup frequency + location:** Not applicable — user data is in their browser. `**[NEEDS-INPUT]**: Should we provide an export/import feature for users to back up their tasks? This is currently out of scope but would be the only DR mechanism.`
- **Failover procedure:** Not applicable.
- **Tested cadence:** Not applicable.

## 16. Runbook Sketch

**Scenario 1: Application fails to load (blank screen)**
- **Symptom:** User navigates to the app URL and sees a blank white page.
- **First command:** Open browser DevTools → Console tab. Look for errors (e.g., "sql.js failed to initialize", "WebAssembly not supported").
- **Escalation:** If the error is WebAssembly-related, the user's browser is too old. Recommend upgrading to a modern browser (Chrome, Firefox, Edge, Safari 14+). If the error is a runtime JS exception, file a GitHub issue with the full console output.

**Scenario 2: Tasks disappear after browser restart**
- **Symptom:** User adds tasks, closes browser, reopens, and tasks are gone.
- **First command:** Open DevTools → Application tab → Local Storage → find the key `web-todo-proofpoint-v3-db`. If it's empty or missing, the data was cleared.
- **Escalation:** Check if the user cleared browser data (cookies/site data) between sessions. If not, file a GitHub issue with browser version and steps to reproduce.

## 17. Out of Scope (this RFC)

- Task editing (modifying title after creation) — deferred to a future RFC if needed.
- Task ordering/sorting — deferred.
- Completed task visibility toggle — deferred.
- Export/import of task data — deferred.
- Dark mode or theme customization — deferred.

## Extension 1 — Task Tagging

### Module Breakdown (delta)
| Module | New / Extended | Public interface | Owns | Depends on |
|---|---|---|---|---|
| `task` | extended | adds `addTag(taskId: string, tag: string): Promise<Task>`, `removeTag(taskId: string, tag: string): Promise<Task>`, `getTasksByTags(tags: string[], logic: 'AND' \| 'OR'): Promise<Task[]>` | extension methods on existing `TaskService` | existing `task` module exports |
| `ui` | extended | adds `TagInput`, `TagBadge`, `TagFilterBar` components | tag-related UI rendering | `task` module (via `ITaskAPI`) |

### Data Model (delta)
- Existing `Task` entity: gains `tags: TEXT` field (comma-separated tag string, additive, default `''`; existing rows get `''` on read via migration sketch below).
- No new entities. Tags are stored as a denormalized comma-separated string on the `Task` row for simplicity (single-user, no tag management UI).

**Schema SQL (delta):**
```sql
ALTER TABLE tasks ADD COLUMN tags TEXT NOT NULL DEFAULT '';
```

**Validation (zod) delta:**
```typescript
const TaskSchema = z.object({
  // ... existing fields unchanged ...
  tags: z.string().default(''),
});
```

### Migration Sketch
- sql.js in-memory DB is recreated on each page load from the `localStorage` blob. No version bump needed — the `ALTER TABLE` is run on first load if the column doesn't exist (checked via `PRAGMA table_info(tasks)`). If column exists, skip migration.
- Existing rows: `tags` defaults to `''` (no tags assigned). No data loss.

### Test Strategy (delta)
- New tests: `task/tagging.test.ts` (addTag, removeTag, getTasksByTags with AND/OR logic, edge cases like empty tags, duplicate tags, non-existent task).
- Existing test suites: must remain green. Integration tests for `ITaskAPI` must be updated to include the new methods.
- UI tests: component tests for `TagInput`, `TagBadge`, `TagFilterBar` using Vitest + jsdom.

### Risks (delta-specific only)
| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Tag string parsing errors (comma in tag name, leading/trailing whitespace) | Tags may be incorrectly parsed or displayed | Medium | Use `trim()` on each tag; strip empty strings from split result; document that tags cannot contain commas (or escape them) |
| Tag filter performance with many tasks (1000+ tasks, each with multiple tags) | Filtering may be slow due to full table scan | Low (text-only tasks are tiny) | Add a `tags` index on the `tasks` table; if performance degrades, consider a separate `task_tags` junction table in a future extension |
| User adds tags to a task, then deletes the task — orphaned tags in filter bar | Filter bar shows tags that no longer exist on any task | Low | On task deletion, recalculate unique tags from remaining tasks; this is already covered by AC #10 in the PRD delta |

### Open Questions
- **[NEEDS-INPUT]** Should tags be free-form text, or should there be a predefined set of tags the user can choose from? (This affects whether we need a `tags` table or can keep the denormalized string approach.)
- **[NEEDS-INPUT]** Should the tag filter support OR logic (show tasks that have any of the selected tags) instead of AND logic? (The PRD delta specifies AND logic, but this may change based on user feedback.)
- **[NEEDS-INPUT]** Should completed tasks be excluded from tag filter results, or should they still appear? (The PRD delta does not specify, but this affects the `getTasksByTags` query.)
