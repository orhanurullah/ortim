---
name: typescript-imports-from-locked-stack
description: Only import third-party libraries that are declared in the locked stack; never invent dependencies.
audience: [worker, reviewer]
triggers:
  language: [TypeScript]
---

# Stack-anchored imports

The project's locked stack lists the libraries this codebase uses. Worker
output may only import third-party packages from that list. Inventing a
dependency at write-time breaks `npm install`, hides at the type system
level, and forces an unplanned dependency review.

## Rules

- **DO** import only from packages declared in the locked stack's
  `key_libraries`, plus their well-known peer dependencies (`react-dom`
  for `react`, `@types/*` for typed runtimes).
- **DO** prefer the language's standard library when a small helper is
  needed. `crypto.randomUUID()` is already in modern Node — pulling in
  `uuid` "just in case" is an invented dependency.
- **DO NOT** import packages just because the model has seen them
  elsewhere. If you need a library that isn't in the stack, surface it
  in the WorkerOutput summary as an unresolved need — do not write the
  import.
- **DO NOT** assume a transitive dependency is callable. If `vite`
  re-exports something from `rollup`, that is an internal detail; only
  import from packages that the stack explicitly names.

## Worker output checklist

Before emitting each file, list the third-party imports the file uses
and confirm each one is in the locked stack:

1. `react`, `react-dom`, `sql.js`, `zod`, `vitest`, ... → ✅ in stack
2. `uuid` (not in stack) → ❌ either use `crypto.randomUUID()` or
   surface the need in the summary
3. `lodash`, `axios`, `commander` (not in stack) → ❌ same — do not
   import

## Code examples

```ts
// Locked stack key_libraries: [react, sql.js, zod]
// Native Node: crypto.randomUUID is fine.

// ✅ correct
import { z } from 'zod';
import initSqlJs from 'sql.js';

function newId(): string {
  return crypto.randomUUID();
}

// ❌ wrong — `uuid` is not in the locked stack
import { v4 as uuidv4 } from 'uuid';
```

## Reviewer rubric

If a Worker output imports a package not in the locked stack:

- Mark the offending file's criteria as `fail` and add an L1 violation:
  `"imported '<package>' which is not in the locked stack's key_libraries"`.
- Cite this skill by name in the verdict reason.
- Suggest the closest in-stack alternative (or stdlib) in `suggestions`.
