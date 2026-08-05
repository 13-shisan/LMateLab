# VASP Database Hardening Design

## Goal

Make the personal VASP database reliable and readable on desktop and mobile, while keeping the existing ASE databases and URL contract compatible.

## Ordered Scope

1. Remove the fixed-height table clip so every returned row is visible.
2. Resolve owner availability from real database references and correct stale registered paths.
3. Introduce a presentation schema for labels, units, precision, empty values, and paths.
4. Expose database freshness and provide a guarded PBS refresh entrypoint without running the 28-dataset job on the web host.
5. Persist the `only_last` index and include every filter dimension in cache identity.
6. Eliminate the initial tasks/columns request waterfall.
7. Add newest/oldest ordering plus ID/formula search, and present `only_last` as a clear two-mode control.
8. Make the controls, periodic table, and task table fit mobile viewports without document-level horizontal overflow.

## Architecture

Backend table concerns move into a focused `vasp_table_schema` service. It owns default columns, display metadata, formatting hints, and query validation. The tasks endpoint remains backward compatible while adding `sort_order` and `query`; filtered ID caches include row filters and query state. Database owner metadata is computed from resolved references, including existence and latest source modification time.

The frontend keeps the existing page route but extracts the task surface into a dedicated component and stylesheet. The component consumes backend column metadata, formats values without losing access to raw values, provides a responsive toolbar, and lets the table scroll only inside its own region. Desktop keeps a dense scientific table; mobile uses prioritized columns and a row detail disclosure instead of forcing a 1600px table into the viewport.

The ingestion script remains PBS-only. A guarded refresh wrapper verifies `qsub`, records submission state, and refuses to run the heavy scan directly on the web host. The UI reports source modification time and stale status. The current environment cannot reach the PBS submit host, so operational refresh is a separately reported deployment prerequisite rather than an unsafe local fallback.

## Behavior

- Existing `only_last=0|1` URLs continue working.
- New visits default to final records (`only_last=1`) and newest-first ordering.
- The mode labels are `全部离子步` and `每个目录最终记录`.
- Search accepts a numeric row ID or a case-insensitive formula fragment.
- Default columns use Chinese labels and scientific units; original keys and raw values remain available in tooltips.
- Owners with no existing personal or upload database are disabled and show the real missing reason.
- Desktop and mobile never hide returned rows or create document-level horizontal overflow.

## Verification

- Backend unit tests cover owner availability, cache identity, persistent final-record caches, search, sorting, and metadata.
- Frontend unit tests cover labels and scientific formatting.
- Playwright verifies 20 of 20 rows are visible, ordering/search interactions work, and 1440px/390px layouts have no document overflow.
- Production tests, lint, build, container health, and live API checks must pass before completion.
