---
name: react-dependency-injection
description: Construct adapters/services ONCE at App root; pass via props or Context. Never `new X()` inside event handlers or rendered children.
audience: [worker, reviewer]
triggers:
  language: [TypeScript]
  app_class: [web]
  keywords: [wire, wiring, integrate, integration, app component, context provider, usecontext]
---

# React dependency injection

L1's "Dependency Injection" principle says business logic must receive
its dependencies rather than construct them. In a React + Vite SPA, the
canonical shape is:

1. **Build the dependency graph ONCE at the App root** — the highest
   component that owns the lifecycle.
2. **Pass dependencies down via props or React Context** — never via
   inline `new` inside handlers.
3. **Use `useMemo` if the construction has side effects** so React's
   re-render doesn't recreate the adapter on every keystroke.

Proof-point v2 T-007 (`task-ui/App.tsx`) violated this: `new
SqljsAdapter()` and `new TaskService(adapter)` lived inside the
`handleCreate`/`handleToggle`/`handleDelete` event handlers. Every user
click re-opened a SQLite database, lost state, and tripped the L1 DI
rule. The Reviewer correctly flagged this as a blocker.

## The rule

**Construct adapters and services at the highest component that owns
their lifecycle. Pass them down. Never `new X()` inside an event handler,
`useEffect` cleanup, or `JSX render path`.**

## Pattern A — props down from App (small apps)

```tsx
// App.tsx — owns the lifecycle, builds once
import { useMemo } from 'react';
import { SqljsAdapter } from '../persistence';
import { TaskService } from '../task-service';
import { TaskList } from './TaskList';

export function App() {
  const service = useMemo(() => {
    const adapter = new SqljsAdapter();
    return new TaskService(adapter);
  }, []);

  return <TaskList service={service} />;
}

// TaskList.tsx — receives via props
interface TaskListProps {
  service: ITaskService;
}

export function TaskList({ service }: TaskListProps) {
  const handleCreate = (title: string) => {
    service.create(title);  // ✅ uses injected dependency
  };
  // ...
}
```

## Pattern B — React Context (deep trees)

When the dependency must reach components more than 2-3 levels deep, use
Context to avoid prop drilling:

```tsx
// services.tsx — context + provider
import { createContext, useContext, useMemo, type ReactNode } from 'react';

interface Services {
  taskService: ITaskService;
}

const ServicesContext = createContext<Services | null>(null);

export function ServicesProvider({ children }: { children: ReactNode }) {
  const value = useMemo<Services>(() => {
    const adapter = new SqljsAdapter();
    return { taskService: new TaskService(adapter) };
  }, []);
  return <ServicesContext.Provider value={value}>{children}</ServicesContext.Provider>;
}

export function useTaskService(): ITaskService {
  const ctx = useContext(ServicesContext);
  if (!ctx) throw new Error('useTaskService must be used within <ServicesProvider>');
  return ctx.taskService;
}

// App.tsx — wraps children
export function App() {
  return <ServicesProvider><TaskList /></ServicesProvider>;
}

// TaskList.tsx — pulls via hook
export function TaskList() {
  const service = useTaskService();  // ✅
  // ...
}
```

## Anti-patterns (DI violations — Reviewer will fail your task)

### ❌ Inline `new` in event handler

```tsx
export function App() {
  const handleCreate = (title: string) => {
    const adapter = new SqljsAdapter();  // ❌ rebuilt every click
    const service = new TaskService(adapter);
    service.create(title);
  };
}
```

### ❌ Module-level singleton via top-of-file `new`

```tsx
const adapter = new SqljsAdapter();   // ❌ runs at import time
const service = new TaskService(adapter);

export function App() {
  return <button onClick={() => service.create('x')}>...</button>;
}
```

Module-level construction looks like injection but isn't:
- It runs at import time, before React mounts → can't depend on browser
  features that need `document.body` or async setup.
- It's globally shared → testing requires module-mocking gymnastics.
- It hides the dependency edge from Reviewer's render-path scan.

### ❌ Constructing inside JSX

```tsx
return (
  <TaskList service={new TaskService(new SqljsAdapter())} />  // ❌
);
```

Same shape as the inline-handler problem: re-runs on every render.

## Worker checklist before emitting an App/wiring file

1. List the adapters and services this file needs.
2. Put their construction inside ONE `useMemo` at the top of the
   highest-owning component (usually `App`).
3. Pass them down via props (Pattern A) or Context (Pattern B). Choose
   props when the consumer is at most 2 levels deep; Context otherwise.
4. Grep your file for `new ` after writing. If `new ` appears inside an
   event handler, `useEffect` callback body, or JSX expression, move it
   into the `useMemo`.

## Reviewer guidance

Flag as `l1_violations` with citation `Dependency Injection` whenever
you see:
- `new ServiceName(` inside an arrow function body that's used as an
  event handler (`onClick`, `onSubmit`, `onChange`),
- `new ServiceName(` at module top-level when the constructed object has
  any non-trivial setup (DB open, network handle),
- `new ServiceName(` inside JSX (`<X service={new TaskService()} />`).

Acceptable: `new ServiceName(` inside `useMemo`/`useState` initializer
at the top of a component, or in a `ServicesProvider`-style component
that exists specifically to wire dependencies.
