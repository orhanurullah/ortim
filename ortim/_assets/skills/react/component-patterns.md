---
name: react-component-patterns
description: Functional components + hooks only; one component per file; props typed via interface; co-located test file when behavior is non-trivial.
audience: [worker, reviewer]
triggers:
  language: [TypeScript]
  app_class: [web]
  keywords: [component, ui, render, props, react, tsx, jsx, hook]
---

# React component patterns

This project uses modern React: functional components, hooks, strict TS.
Class components and legacy patterns are out.

## Rules

- **DO** write components as named function declarations with a typed
  props interface: `export function TaskItem(props: TaskItemProps) { ... }`.
- **DO** one component per file. The file name matches the component
  name in PascalCase: `TaskForm.tsx`, `TaskList.tsx`.
- **DO** type props with an `interface` named `<Component>Props`. Use
  `?` for optional props. Default values via destructuring with `= ...`.
- **DO** use hooks for state: `const [tasks, setTasks] = useState<Task[]>([])`.
  Side effects go in `useEffect`. Derived values in `useMemo` or just
  inline if cheap.
- **DO** keep event handlers small and named: `handleSubmit`,
  `handleDelete`. Inline arrow functions are acceptable for trivial
  cases.
- **DO NOT** write class components. No `React.Component`, no
  `componentDidMount`, no `this.state`.
- **DO NOT** mix concerns. A component file imports React + hooks +
  child components + types — it should not also export utility
  functions, data fetchers, or schemas. Move those into the module's
  `index.ts` or a sibling file.
- **DO NOT** pass props as `any`. Even for a quick PoC, the props
  interface is mandatory.

## Worker output checklist

For every `*.tsx` file in your output:

1. Confirm the file exports exactly one component (or one wrapper
   alongside it — e.g. a `forwardRef` wrapper).
2. Confirm the component is a function, not a class.
3. Confirm props are typed via `interface <Component>Props` (or
   `type ... = ...` when you really need a union/intersection).
4. Confirm hooks are called at the top level of the component (no
   conditional hooks).
5. If the component has runtime behavior (form submission, click
   handler with side effects, useEffect that fetches), pair it with a
   `*.test.tsx` per the `typescript-vitest-co-located` skill.

## Code examples

```tsx
// ✅ correct — typed props, named function, one component per file
import { useState } from 'react';

export interface TaskFormProps {
  onCreate: (title: string) => void;
  disabled?: boolean;
}

export function TaskForm({ onCreate, disabled = false }: TaskFormProps) {
  const [title, setTitle] = useState('');

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (title.trim()) {
      onCreate(title.trim());
      setTitle('');
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <input value={title} onChange={(e) => setTitle(e.target.value)} />
      <button type="submit" disabled={disabled}>Add</button>
    </form>
  );
}
```

```tsx
// ❌ wrong — class component
export class TaskForm extends React.Component<TaskFormProps, State> { ... }
```

## Reviewer rubric

For each `.tsx` file in Worker output:

- If the component is a class → mark `fail` + L1 violation
  `"react-component-patterns: class component used; this project mandates functional components"`.
- If props are not typed → mark `fail` + L1 violation `"react-component-patterns: untyped props"`.
- If hooks appear conditionally → mark `fail` + L1 violation
  `"react-component-patterns: hook called conditionally"`.
- Cite this skill by name in every violation.
