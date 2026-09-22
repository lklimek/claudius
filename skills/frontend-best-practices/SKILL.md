---
name: frontend-best-practices
description: "This skill should be used when writing, reviewing, or discussing frontend code — TypeScript, React/Vue/Svelte, CSS, accessibility, and testing."
allowed-tools: Read
---

# Frontend Best Practices

## Standards
- TypeScript strict mode; no `any` without explicit justification (`unknown` + narrowing); ESLint (+ jsx-a11y) + Prettier per project config; `tsc --noEmit`
- Vitest or Jest with Testing Library (query by role/label, not test IDs), MSW for API mocking, minimum 80% coverage; axe-core + manual keyboard testing; Lighthouse CI and bundle-size budgets (vite-plugin-visualizer / webpack-bundle-analyzer)
- One-line JSDoc per public function, expanded only for complex logic

## Practices
- Semantic HTML over generic divs; CSS custom properties for theming; component composition over prop drilling; lazy loading for code splitting; optimistic UI where appropriate; error boundaries with fallback UI; accessible forms (labels, error messages, focus management); progressive enhancement

## Patterns
- State: React Context for simple, Zustand/Jotai for complex, Redux only when justified. Server state: TanStack Query or SWR, not raw `useEffect`. Forms: React Hook Form or Formik with Zod/Yup. Routing: the framework router. Styling: CSS Modules, Tailwind, or styled-components — consistent with the project. Errors: boundaries per route/feature, toasts for recoverable errors

## Common Pitfalls
- Don't use `any` — use `unknown` and narrow, or define proper types
- Don't mutate state directly — return new references
- Don't fetch in useEffect without cleanup — use a data fetching library
- Don't skip `key` props on lists or use array index as key for dynamic lists
- Don't inline object/function literals in JSX props — causes re-renders
- Don't ignore `useEffect` dependency arrays or suppress the lint rule
- Don't use `dangerouslySetInnerHTML` without sanitization (XSS risk)
- Don't store derived state — compute during render
- Don't forget `loading`, `error`, and `empty` states in data-driven components

## Package.json
- `peerDependencies` for shared framework deps in libraries; accurate `devDependencies` vs `dependencies`; `npm audit`/`pnpm audit` before releases

## Design Quality

High-fidelity UI work: the `frontend-design:frontend-design` skill, when available.

## Code Review Checklist
- TypeScript strict mode compliance, no unjustified `any`
- Component composition and prop management
- Accessibility: ARIA attributes, keyboard navigation, semantic HTML
- CSS/styling consistency and maintainability
- State management patterns appropriate to scope
- DRY compliance: duplicated components, repeated logic
- Naming clarity: components, hooks, utilities, types
- Performance: unnecessary re-renders, missing memoization, bundle size
- Test quality: component tests, user interaction tests, proper mocking
- Code brevity: flag code that can be expressed in fewer lines without losing clarity

Use `FE-NNN` prefix for all findings.
