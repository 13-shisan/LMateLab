# LMateLab Dashboard App Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved persistent sidebar dashboard shell and connect it only to existing routes and real data.

**Architecture:** A route-aware `AppShell` wraps all authenticated dashboard routes. A pure navigation configuration supplies labels, icons, groups, active aliases, and dashboard shortcuts; the dashboard consumes existing report data and configuration rather than invented task status.

**Tech Stack:** React 19, React Router 7, lucide-react, CSS, Node test runner, Vite.

---

### Task 1: Navigation Model

**Files:**
- Create: `frontend/src/config/appNavigation.js`
- Create: `frontend/tests/appNavigation.test.mjs`
- Modify: `frontend/package.json`

- [x] Write failing tests for exact dashboard matching, nested database routes, detail-route aliases, and unrelated routes.
- [x] Run `npm test` and confirm the module is missing.
- [x] Add grouped navigation data and pure `isNavigationItemActive` / `getPageMeta` helpers.
- [x] Run `npm test` and confirm all navigation tests pass.

### Task 2: Shared Authenticated Shell

**Files:**
- Create: `frontend/src/components/AppShell.jsx`
- Create: `frontend/src/components/AppShell.css`
- Modify: `frontend/src/App.jsx`

- [x] Add one authenticated layout route around every `/dashboard` child route.
- [x] Render the desktop sidebar, mobile drawer, compact top bar, user menu, and logout behavior.
- [x] Close transient UI on route changes and Escape.
- [x] Build and verify all existing routes still resolve.

### Task 3: Remove Duplicated Global Bars

**Files:**
- Modify: `frontend/src/pages/Dashboard.jsx`
- Modify: `frontend/src/pages/AcademicReports.jsx`
- Modify: `frontend/src/pages/Changelog.jsx`
- Modify: `frontend/src/pages/issues.jsx`
- Modify: `frontend/src/pages/db/DbLayout.jsx`
- Modify: `frontend/src/pages/papers/PapersLayout.jsx`
- Modify: `frontend/src/pages/server_monitor/ServerMonitorLayout.jsx`
- Modify: `frontend/src/pages/agents/AgentLayout.jsx`
- Modify: `frontend/src/pages/notes/TasksLayout.jsx`
- Modify: `frontend/src/pages/notes/TasksEntry.jsx`

- [x] Remove only duplicated `Topbar` imports and renders.
- [x] Preserve page-local breadcrumbs, filters, menus, and business content.
- [x] Run ESLint on the changed files and address errors introduced by this refactor.

### Task 4: Dashboard Redesign

**Files:**
- Modify: `frontend/src/pages/Dashboard.jsx`
- Create: `frontend/src/pages/Dashboard.css`

- [x] Replace modal-based module navigation with direct route links.
- [x] Show authenticated user, configured database count, existing reports, platform status, and existing external links.
- [x] Do not render visual-concept task names, progress values, or timestamps.
- [x] Match the approved desktop and mobile density and spacing.

### Task 5: Verification and Deployment

**Files:**
- Modify only files required by verified failures.

- [x] Run `npm test`.
- [x] Run ESLint on the changed JavaScript files.
- [x] Run `npm run build`.
- [x] Deploy through the existing Docker Compose frontend service.
- [x] Log in and capture desktop and 390x844 screenshots.
- [x] Verify sidebar routes, drawer, user menu, overflow, and browser console.
- [x] Commit the redesign separately and confirm `git status --short --branch` is clean.
