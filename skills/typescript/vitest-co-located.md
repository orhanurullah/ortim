---
name: typescript-vitest-co-located
description: Every TS source file with runtime behavior gets a co-located *.test.ts file with vitest assertions.
audience: [worker]
triggers:
  language: [TypeScript]
  keywords: [test, vitest, behavior, criteria, expect, assert]
---

# Co-located vitest tests

When the task description or its acceptance criteria mention runtime
behavior (creates an object, throws on bad input, returns a list, etc.),
the Worker must emit at least one co-located `*.test.ts` (or
`*.test.tsx` for React components) file under the same module_scope as
the implementation.

## Rules

- **DO** put the test file next to the impl: `task-service/index.ts`
  pairs with `task-service/index.test.ts`. Alternatively, group tests
  under `task-service/__tests__/<name>.test.ts` — both layouts are
  acceptable; pick one and stick to it within a module.
- **DO** write one `describe` per public function and one `it` per
  acceptance criterion that mentions runtime behavior. Mirror the
  criterion's words in the `it` name so the test is grep-able against
  the criterion list.
- **DO** use `expect(...).toThrow(...)`, `expect(...).toEqual(...)`,
  `expect(...).resolves.toBe(...)` from vitest. The runner will execute
  the tests; criteria that depend on runtime behavior are
  `unverifiable` without them.
- **DO NOT** test private internals. Only test through the module's
  public barrel.
- **DO NOT** emit a `*.test.ts` file with a single `it.skip` or `expect(true).toBe(true)` stub — that triggers the Reviewer's
  meaningful-assert check.

## Worker output checklist

1. List each acceptance criterion that contains a verb like *returns*,
   *throws*, *creates*, *deletes*, *updates*, *renders*, *fetches*,
   *parses*, *validates*.
2. For each such criterion, plan an `it("<criterion text>")` block
   somewhere in your test files.
3. Emit the implementation **and** the test file in the same
   WorkerOutput. Splitting them across tasks defeats the criterion
   check.

## Example

```ts
// task-service/index.ts
export function createTask(title: string): Task { ... }

// task-service/index.test.ts
import { describe, it, expect } from 'vitest';
import { createTask } from './index';

describe('createTask', () => {
  it('returns a Task object with title, completed=0, created_at', () => {
    const t = createTask('Buy milk');
    expect(t.title).toBe('Buy milk');
    expect(t.completed).toBe(0);
    expect(t.created_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it('throws ZodError on whitespace-only title', () => {
    expect(() => createTask('   ')).toThrow();
  });
});
```
