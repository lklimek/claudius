---
name: frontend-best-practices
description: "Frontend best practices — TypeScript, React/Vue/Svelte, CSS, accessibility, testing. Use when writing, reviewing, or discussing frontend code."
allowed-tools: Read
---

# Frontend Best Practices

## Technical Standards
- **Language**: TypeScript with strict mode enabled
- **Code Style**: ESLint + Prettier, consistent with project config
- **Type Safety**: No `any` types without explicit justification
- **Testing**: Vitest or Jest with Testing Library, minimum 80% coverage
- **Accessibility**: axe-core automated checks, manual keyboard testing
- **Performance**: Lighthouse CI, bundle size budgets
- **Documentation**: One-line JSDoc for every public function; expand only for complex logic

## Best Practices
- Semantic HTML elements over generic divs
- CSS custom properties for theming
- Component composition over prop drilling
- Lazy loading for code splitting
- Optimistic UI updates where appropriate
- Proper error boundaries and fallback UI
- Accessible forms with proper labels, error messages, focus management
- Progressive enhancement

## Common Patterns
- **State Management**: React Context for simple state, Zustand/Jotai for complex; Redux only when justified
- **Data Fetching**: TanStack Query or SWR for server state, avoid raw useEffect
- **Forms**: React Hook Form or Formik with Zod/Yup schema validation
- **Routing**: Framework router (Next.js App Router, React Router, Vue Router)
- **Styling**: CSS Modules, Tailwind CSS, or styled-components — consistent with project
- **Testing**: Testing Library (query by role/label, not test IDs), MSW for API mocking
- **Error Handling**: Error boundaries per route/feature, toast for recoverable errors

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
- Use `peerDependencies` for shared framework deps in libraries
- Keep `devDependencies` vs `dependencies` accurate
- Audit with `npm audit` or `pnpm audit` before releases

## Design Quality

For high-fidelity UI work, invoke the `frontend-design:frontend-design` skill.

## Code Quality Tools
- **Linting**: ESLint with TypeScript plugin
- **Formatting**: Prettier
- **Type Checking**: `tsc --noEmit`
- **Testing**: `vitest run --coverage`
- **Accessibility**: eslint-plugin-jsx-a11y, axe-core
- **Bundle Analysis**: vite-plugin-visualizer or webpack-bundle-analyzer

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
