---
name: typescript-sql-mock-patterns
description: When mocking a run(sql, params)-style db adapter, the SQL string determines which params positions are bound. Inspect the SQL before destructuring.
audience: [worker]
triggers:
  language: [TypeScript]
  keywords: [mock, db-adapter, persistence, vitest, sql.js, sqlite]
---

# SQL mock destructuring — read the SQL, then the params

When a vitest test mocks a `run(sql, params)`-style database adapter,
the **SQL string** dictates which positions in `params` are actually
bound. Hardcoded literals in the SQL (e.g. `VALUES (?, ?, 0, ?)`) do
**not** consume a slot in the params array.

A mock that blindly destructures one variable per column will misread
the data on every call where the impl uses any literal — and the bug
is invisible until a test assertion finally inspects the wrong field.

## The trap

Production code (correct):

```ts
// task-service/index.ts
run(
  'INSERT INTO tasks (id, title, completed, created_at) VALUES (?, ?, 0, ?)',
  [id, validatedTitle, created_at],
);
```

Buggy mock (wrong — destructures 4 names from a 3-element array):

```ts
// task-service/index.test.ts  ❌
} else if (sql.startsWith('INSERT')) {
  const [id, title, completed, created_at] = params;
  // completed = (the timestamp string)
  // created_at = undefined
  store.set(id, { id, title, completed, created_at });
}
```

The SQL has 4 placeholders in the column list but **only 3 `?`** in
`VALUES (...)` — the `0` is a literal. So `params.length === 3`, not 4.
Production code is right; the mock just doesn't match what the impl
actually sends.

## The rule

**Count the `?` in the SQL string. Destructure exactly that many
positions. Use the SQL's column list and literals to compute the
remaining fields.**

Correct mock for the INSERT above:

```ts
} else if (sql.startsWith('INSERT')) {
  const [id, title, created_at] = params;     // 3 ? in SQL → 3 vars
  store.set(id, { id, title, completed: 0, created_at });  // literal from SQL
}
```

## Worker checklist before emitting a mock implementation

1. **Read the production SQL string verbatim.** Find every `?`. That's
   the bound-positions count.
2. **Compare to the params array length** the impl passes — they must
   be equal. If the impl is `run(sql, [a, b, c])`, the SQL has exactly
   3 `?`.
3. **Destructure exactly that many names** from `params`. No more, no
   fewer.
4. **For columns with hardcoded literals in the SQL** (`0`,
   `CURRENT_TIMESTAMP`, `'pending'`), bake the same literal into the
   mocked row object — do **not** read it from `params`.
5. **For UPDATE that toggles a flag** (e.g. `UPDATE tasks SET
   completed = 1 WHERE id = ?`), the mock should set the flag to the
   literal `1`, not pull it from `params`. The params array contains
   only the WHERE-clause binds.

## Common SQL patterns and their mock shape

| SQL | `?` count | Mock destructure |
|---|---|---|
| `INSERT ... VALUES (?, ?, 0, ?)` | 3 | `const [id, title, created_at] = params;` |
| `UPDATE t SET completed = 1 WHERE id = ?` | 1 | `const [id] = params;` |
| `UPDATE t SET title = ? WHERE id = ?` | 2 | `const [title, id] = params;` |
| `DELETE FROM t WHERE id = ?` | 1 | `const [id] = params;` |
| `SELECT * FROM t WHERE id = ?` | 1 | `const [id] = params;` |
| `SELECT * FROM t ORDER BY created_at DESC` | 0 | no destructure — return all rows |

## Anti-pattern to avoid

Do **not** infer the destructure from the function signature of the
caller (e.g. "the createTask function takes `title`, so destructure
title from params"). The caller's signature is irrelevant — only the
SQL string and its `?` count matter.
