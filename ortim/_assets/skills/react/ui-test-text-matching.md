---
name: react-ui-test-text-matching
description: UI text and its test assertion must agree on decoration. Default to bare strings in UI unless the criterion names decoration; if you decorate (emoji, icons, prefix), use partial-match in the test.
audience: [worker, reviewer]
triggers:
  language: [TypeScript]
  app_class: [web]
  keywords: [toast, banner, notification, warning, alert, message, label, status text, empty state, error message, success message]
---

# UI text ↔ test assertion symmetry

A recurring drift: the Worker writes user-friendly UI text with emoji or
icon prefix (`"⚠️ You have over 1000 tasks"`, `"✓ Task created"`,
`"❌ Failed to load"`), but the test was written to assert the bare
string (`"You have over 1000 tasks"`). The test fails because
`getByText("You have over 1000 tasks")` requires exact match by default
and the emoji prefix is part of the rendered text node.

Proof-point v3 T-006 hit this: `<p>⚠️ You have over 1000 tasks. Consider archiving.</p>`
in the component, but the test was `expect(screen.getByText('You have over 1000 tasks. Consider archiving.')).toBeInTheDocument()`. Test failed.
Worker self-corrected on attempt 2 by dropping the emoji. One wasted
attempt is the cost of an absent rule.

## The rule

**The UI text the user sees and the string the test asserts must agree
on decoration.** Two ways to keep them in agreement:

1. **(Default)** Write bare strings in the UI. No emoji, no icon prefix
   inside the text node. If you want a visual cue, use a sibling icon
   element (`<Icon>` + `<span>{text}</span>`) so the text node is clean.
2. **(Opt-in)** Decorate the text only when the acceptance criterion
   explicitly names the decoration ("show a warning icon", "prefix with
   ✓"). In that case, use partial-match in the test
   (`screen.getByText(/over 1000 tasks/)` regex, or `toHaveTextContent`
   which substring-matches), not exact-match `getByText('...')`.

## Decision flow

Before emitting UI text, the Worker asks:

```
Does the acceptance criterion or RFC §7 explicitly mention an icon /
emoji / prefix decoration for this text?

├── NO  → Write the bare string in the UI. Match the criterion text
│         verbatim. Tests stay with exact-match `getByText(...)`.
│
└── YES → Decorate as instructed. Write the test with partial-match:
          screen.getByText(/<core phrase>/) or
          element.toHaveTextContent('<core phrase>').
```

## Examples

### ❌ Wrong — emoji in UI, exact-match in test

```tsx
// component
<p>⚠️ You have over 1000 tasks. Consider archiving.</p>
```
```ts
// test
expect(
  screen.getByText('You have over 1000 tasks. Consider archiving.')
).toBeInTheDocument();  // FAILS — emoji prefix breaks exact match
```

### ✅ Right — bare string both sides (default path)

```tsx
<p>You have over 1000 tasks. Consider archiving.</p>
```
```ts
expect(
  screen.getByText('You have over 1000 tasks. Consider archiving.')
).toBeInTheDocument();
```

### ✅ Right — decoration via sibling icon, bare text node

```tsx
<p>
  <WarningIcon aria-hidden="true" />
  <span>You have over 1000 tasks. Consider archiving.</span>
</p>
```
```ts
// Text node is clean; exact-match still works.
expect(
  screen.getByText('You have over 1000 tasks. Consider archiving.')
).toBeInTheDocument();
```

### ✅ Right — criterion names decoration; partial-match in test

Criterion: *"warning banner shows ⚠️ prefix and 'over 1000 tasks' phrase"*

```tsx
<p>⚠️ You have over 1000 tasks. Consider archiving.</p>
```
```ts
const banner = screen.getByRole('alert');
expect(banner).toHaveTextContent('over 1000 tasks');  // partial match
expect(banner.textContent).toMatch(/^⚠️/);            // explicit emoji check
```

## What this is NOT

- This is **not** a ban on emoji in production UIs. Emoji are fine when
  the criterion calls for them.
- This is **not** about i18n. Localization is a separate concern; this
  rule applies within a single locale.
- This is **not** about `aria-label` mismatch — that's an accessibility
  rule, separate skill territory.

## Reviewer guidance

If the Worker output shows a UI string that includes emoji / icon prefix
AND the acceptance criterion text does NOT mention that decoration, mark
the criterion `fail` with `code_quote` containing the literal decorated
string and `evidence`: *"UI text decorated with `<prefix>`; criterion
asserts the bare string `'<criterion text>'`; either drop the decoration
or rewrite the test to use partial-match."* Cite this skill in the
verdict so the Worker knows where the rule lives.
