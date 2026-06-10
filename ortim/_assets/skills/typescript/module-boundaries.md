---
name: typescript-module-boundaries
description: Cross-module imports go through the public barrel, never through internal file paths.
audience: [worker, reviewer]
triggers:
  language: [TypeScript]
---

# TypeScript module boundaries

When a task in module `A` needs a symbol that belongs to a sibling module `B`,
import from the module root only.

## Rules

- **DO** import from the module root: `import { foo } from '../B'` — the
  module's `index.ts` (or `index.tsx`) is the only public surface.
- **DO NOT** import from internal files: `import { foo } from '../B/internal.ts'`
  bypasses the module boundary and tightly couples task A to B's private
  layout.
- **DO** re-export shared types from the module root if multiple sibling
  modules need them. Never reach into `../B/types.ts` directly.
- **Module ownership is transitive**: code in module A may import from
  module B only if the architecture's RFC §7 lists B as a dependency of A
  (or as a shared `shared/` module). Inferring the dependency from
  "this symbol happens to exist in B" is a boundary violation.

## Worker output checklist

Before emitting each file, mentally walk the imports:

1. Is every `import ... from '...'` either a same-module relative path,
   a sibling-module root path, or an `npm` package from the locked stack?
2. Does the symbol you're importing actually exist in the *barrel* (the
   `index.ts`) of the target module — not just somewhere in its tree?
3. If a sibling module doesn't export what you need, **do not** create
   the file in that module. Surface the missing export in your summary
   so the operator can re-task.

## Code examples

```ts
// ✅ correct — barrel import from sibling module
import { createTask, deleteTask } from '../task-service';

// ❌ wrong — reaches into a sibling module's internal file
import { createTask } from '../task-service/crud.ts';

// ❌ wrong — imports a function the sibling module never exported
import { internalHelper } from '../task-service';
// (would be a Reviewer rejection: "no exported member 'internalHelper'")
```

## Reviewer rubric

If a Worker output contains an import that violates the rules above:

- Mark every acceptance criterion that depends on the offending file as
  `fail` (not `partial`, not `unverifiable`) — the code does not satisfy
  the criterion as written.
- Cite this skill by name in the verdict reason:
  `"violates skill typescript-module-boundaries: imports `../task-service/crud.ts` directly instead of via the barrel"`.
- Add an L1 violation entry: `"cross-module boundary breach"`.
