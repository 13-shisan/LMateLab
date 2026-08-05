# VASP Task Detail Hardening Design

## Goal

Rebuild the VASP task-detail surface so the crystal viewer stays inside its panel, the page is usable on desktop and mobile, unavailable electronic-property outputs do not generate eager 404 requests, and task-detail APIs expose only data required by the UI.

The existing task-detail route remains the canonical full-detail experience. The table row ID continues to open it, while the misleading `详情` row action is renamed to `输入参数` because that action opens calculator parameters rather than the full task page.

## Confirmed Problems

1. 3Dmol inserts an absolutely positioned canvas into a statically positioned host. The host is at approximately `x=557, y=286`, while the canvas renders at `x=0, y=0`, which causes the structure to escape its card.
2. The page root uses a fixed `240px 1fr` grid and several fixed two-column grids. At a 390px viewport the document is 726px wide.
3. Band and DOS requests run sequentially on every route visit. Record 237943 has neither output, so every visit produces two avoidable 404 responses and console errors.
4. The detail response returns the complete ASE `row.data` object, including internal source paths and unrelated data.
5. Plot responses include the resolved server work directory even though the browser does not use it.
6. 3Dmol is loaded from an unversioned third-party runtime script, making rendering dependent on external availability and mutable remote code.
7. The left table of contents consumes scarce width and uses English labels inconsistent with the rest of the operational UI.

## User Experience

### Navigation and identity

- Keep `/dashboard/db/vasp/task/:dbKey/:rowId` as a full page.
- Use a compact page header containing the formula, record ID, database name, and a clear `返回列表` command.
- Replace the fixed left table of contents with a compact in-page section navigation row. It may remain sticky on desktop and becomes horizontally scrollable on mobile.
- Preserve `location.state.backTo` so returning restores the exact database filters and page.
- Rename the table action from `详情` to `输入参数`; the linked record ID remains the full-detail entry.

### Summary and structure

- Present the structure viewer and task summary in one un-nested surface.
- Desktop uses a bounded two-column layout with the viewer as the larger column; mobile stacks viewer then summary.
- The viewer host is `position: relative`, has a responsive aspect ratio with bounded height, clips its own canvas, and has a stable minimum size.
- A `ResizeObserver` resizes and re-renders the 3Dmol viewer when its host changes size.
- Loading, missing-library, invalid-structure, and rendering-error states are visible inside the viewer bounds rather than leaving a blank area.
- Basic values use the same bounded precision and Chinese labels as the database table.

### Scientific sections

- `晶体结构` contains lattice values, derived properties, and the fractional-coordinate table.
- Atomic coordinates show the first ten rows by default and can expand without changing column widths.
- `电子性质` uses tabs for band and DOS. A tab is disabled with an explicit unavailable state when the backend reports that the required source file is missing.
- The active available tab loads on demand. Switching tabs fetches that plot once and reuses the in-memory result.
- Export commands are enabled only for formats supported by the record. Structure export remains available whenever the ASE row can produce atoms.
- Remove the disabled `Phonon（待实现）` control because it is not an actionable feature.

### Mobile behavior

- At 390px, document width must equal viewport width.
- All page grids collapse to one column; labels and values wrap without shrinking into vertical text.
- The viewer remains fully visible and interactive, with a mobile height between 300px and 380px.
- Section navigation and action controls wrap or scroll within their own bounds.
- Tables use internal horizontal scrolling and never widen the document.

## Frontend Architecture

Split the current monolithic `VaspTaskDetail.jsx` into focused units under `frontend/src/pages/db/vasp-detail/`:

- `VaspStructureViewer.jsx`: owns 3Dmol initialization, cleanup, resize, styles, lattice lines, axes, and render states.
- `VaspTaskSummary.jsx`: renders metadata, element legend, and supported exports.
- `VaspCrystalDetails.jsx`: renders lattice, derived properties, and atomic positions.
- `VaspElectronicProperties.jsx`: owns capability-aware tabs, lazy plot loading, cached results, and plot exports.
- `vaspTaskDetailPresentation.js`: centralizes labels, units, precision, and safe display formatting.
- `VaspTaskDetail.css`: owns all desktop/mobile layout rules and viewer constraints.

`VaspTaskDetail.jsx` remains the route orchestrator. It decodes route parameters, fetches one detail payload, owns navigation/error state, and passes narrow props to the focused components.

3Dmol is installed as a fixed npm dependency and dynamically imported inside `VaspStructureViewer`. The external script is removed from `frontend/index.html`. Dynamic import keeps the library out of unrelated route startup.

## Backend Contract

The existing detail endpoint remains compatible at the URL level but returns a reduced response:

```json
{
  "ok": true,
  "db": { "key": "personal:jbwu:Pwjb.db", "dbname": "Pwjb.db" },
  "row": {
    "id": 237943,
    "formula": "Cu4In4P8S24",
    "energy": -192.67317127,
    "fmax": 0.0089,
    "natoms": 40,
    "pbc": [true, true, true]
  },
  "properties": {
    "spacegroup": "P1",
    "bandgap_eV": 1.5708,
    "vbm_eV": 4.3278,
    "cbm_eV": 5.8986
  },
  "capabilities": {
    "structure_export": true,
    "band_plot": false,
    "band_data": false,
    "dos_plot": false,
    "dos_data": false
  },
  "structure": {},
  "crystal": {}
}
```

- Do not return raw `row.data`, `source_dir`, resolved work directories, or calculator parameters from the detail endpoint.
- Keep calculator parameters behind the existing authorized calculator-parameters endpoint.
- Capability detection resolves the source directory through the existing allowed-root and symlink-aware checks, then returns booleans only.
- Plot and data endpoints retain authorization and allowed-path validation but remove `workdir` from successful JSON responses.
- Missing database files and missing rows use HTTP 404 instead of an HTTP 200 payload with `ok: false`.
- Invalid or unauthorized database keys continue to use the existing 403 behavior.

## Security Assessment and Hardening

- Existing database authorization is retained: `resolve_db_for_request` only resolves references in the current user's allowed set.
- Existing source-path validation is retained: paths are resolved before checking membership in allowed roots, which protects against ordinary traversal and symlink escapes.
- Reduce data exposure by replacing raw ASE data with an allowlisted property object.
- Do not send absolute filesystem paths to the client.
- Replace the mutable third-party runtime script with a lockfile-pinned package bundled by Vite.
- React text rendering remains escaped; no raw HTML rendering is introduced.
- Download actions continue to use authenticated requests and server-selected filenames.

No evidence of an IDOR or direct path-traversal vulnerability was found in the reviewed task routes. The hardening addresses unnecessary information disclosure and third-party script trust.

## Error Handling

- The route shows a stable loading skeleton until the detail contract arrives.
- A 403 renders an access-denied state without leaking whether another user's row exists.
- A 404 renders a record-not-found state with a return action.
- Plot failures remain local to the active plot panel and do not break structure viewing.
- Export failures surface a concise visible error rather than an unhandled promise rejection.
- 3Dmol import or render failure produces a viewer-local message and leaves the scientific text sections usable.

## Verification

### Automated

- Backend contract tests cover allowed fields, omitted internal paths, capability flags, missing row 404, and unauthorized database access.
- Frontend presentation tests cover labels, precision, unavailable output states, and absence of fixed desktop-only grid constants.
- React tests or source-contract tests cover lazy plot requests and the `输入参数` label.
- Run focused ESLint, existing frontend tests, backend tests, Vite production build, and `git diff --check`.

### Live browser

Test the route with record 237943 at 1440x1000 and 390x844:

- Canvas bounds remain inside viewer bounds.
- Document width equals viewport width.
- Formula, ID, lattice, properties, and coordinate rows render.
- Unavailable band/DOS do not issue plot requests or console errors.
- Return navigation restores the prior filtered list URL.
- `输入参数` opens the calculator-parameters modal from the table.
- No framework overlay, relevant console error, clipping, overlap, or blank viewer is present.

## Deployment

- Build and test backend/frontend from the canonical production checkout.
- Deploy Python services through `tools/deploy_backend_safely.sh`.
- Build and recreate only the Nginx frontend service after backend health is confirmed.
- Keep rollback image tags and verify public HTTP 200 plus backend container health.
- Commit and push only after desktop/mobile browser verification and a clean production worktree.
