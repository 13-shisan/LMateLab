# Dashboard Equal Panel Height Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the desktop academic-reports panel end at the same vertical position as the Dashboard main column while preserving natural heights in the single-column layout.

**Architecture:** Keep height ownership in the existing CSS Grid. Explicitly stretch direct grid children on desktop and reset alignment to `start` at the existing `1120px` single-column breakpoint.

**Tech Stack:** React, CSS Grid, Node.js test runner, Vite, Playwright CLI

---

### Task 1: Guard and implement responsive panel alignment

**Files:**
- Modify: `frontend/tests/responsiveStyles.test.mjs`
- Modify: `frontend/src/pages/Dashboard.css`

- [ ] **Step 1: Write the failing CSS contract test**

Add a test that requires desktop `.lm-dashboard-grid` to use `align-items: stretch` and the `1120px` media rule to restore `align-items: start`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd frontend && node --test tests/responsiveStyles.test.mjs`

Expected: the new equal-height test fails because the desktop rule still contains `align-items: start`.

- [ ] **Step 3: Implement the minimal layout change**

Change only the grid alignment declarations:

```css
.lm-dashboard-grid {
  align-items: stretch;
}

@media (max-width: 1120px) {
  .lm-dashboard-grid {
    grid-template-columns: 1fr;
    align-items: start;
  }
}
```

- [ ] **Step 4: Run focused and full verification**

Run `npm test`, focused ESLint for `Dashboard.jsx`, `npm run build`, and `git diff --check`. Expected: all commands exit successfully.

- [ ] **Step 5: Deploy and verify rendered geometry**

Rebuild the production frontend container, then use Playwright at `1440x900` to assert the left main column and right reports panel have equal bottom coordinates. At a narrow viewport, assert the grid is single-column with `align-items: start`, no horizontal overflow, and no console errors.

- [ ] **Step 6: Commit and push**

Commit the test, CSS fix, and this plan together with message `fix: align dashboard report panel height`, push `master`, and confirm the remote working tree is clean and synchronized.
