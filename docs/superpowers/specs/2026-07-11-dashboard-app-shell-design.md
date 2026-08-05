# LMateLab Dashboard App Shell Design

## Goal

Replace the portal-style dashboard navigation with a persistent application shell that makes every existing module directly reachable, while keeping all current business routes and APIs intact.

## Approved Visual Direction

- Desktop uses a 232px fixed, scrollable left sidebar.
- Mobile uses a hamburger-triggered drawer with a backdrop and explicit close control.
- A compact top bar shows the current page title, notifications, and a user menu.
- The user menu contains email, language, feedback, changelog, and logout actions.
- Active navigation is derived from the current route, including database and task-detail routes.
- Cards are reserved for dashboard status, reports, and direct workflow entry points. Navigation is never card-to-modal-to-child.

## Navigation Architecture

`appNavigation.js` is the single source of truth for sidebar groups, route labels, active-route aliases, and dashboard shortcuts. `AppShell.jsx` renders this model and owns only navigation UI state. `App.jsx` mounts one authenticated shell around every `/dashboard` route.

Existing page-specific dropdown breadcrumbs remain available inside complex work surfaces, but their duplicated top bars are removed. This keeps local context controls without repeating global navigation.

## Dashboard Data Rules

- Current user comes from the authenticated user record in local storage, refreshed by `RequireAuth`.
- Academic reports continue to use the existing `/academic-reports/latest` API.
- Database and feature counts come from checked-in navigation/module configuration.
- Platform status is presented only as the existing frontend availability state.
- The visual-concept research tasks and timestamps are not production data and must not be rendered.

## Responsive Behavior

- At widths above 900px, sidebar and top bar remain fixed while content scrolls independently.
- At widths at or below 900px, the sidebar becomes an off-canvas drawer.
- Route changes and backdrop clicks close the drawer.
- Focusable buttons have labels and visible focus states; Escape closes open menus and drawers.

## Verification

- Unit tests cover exact and alias route matching.
- ESLint runs on every changed JavaScript file.
- The production Vite build must pass.
- Authenticated Playwright checks cover desktop and 390x844 mobile layouts, active navigation, drawer behavior, user menu, and console errors.
