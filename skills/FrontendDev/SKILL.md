## Frontend Implementation Rules

- TypeScript strict mode enforced (`"strict": true`). No `any` without explicit suppression comment.
- All external API responses validated with Zod at the boundary. Never trust raw fetch data.
- WCAG 2.1 AA minimum: semantic HTML, keyboard navigation, ARIA labels on interactive elements.
- Bundle: code-split by route. Lazy-load anything not needed on first paint. Target <200KB initial JS.
- State colocation: local state first, lift only when shared. Avoid global state for UI-only concerns.
- Error boundaries on every async data-fetching component. Never let a failed fetch crash the page.