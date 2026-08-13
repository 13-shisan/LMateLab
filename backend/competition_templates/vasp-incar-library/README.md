# VASP INCAR template library

This library is an evidence-aware starting point for generating VASP inputs for chemistry calculations. It is not a substitute for convergence tests.

## Start here

1. Use `AGENT_PROMPT.md` as the downstream agent system prompt. `CALLING_GUIDE_CN.md` provides the complete Chinese calling protocol, request schema, routing table, and copy-ready short prompt.
   `request.example.json` is a machine-readable example request for programmatic callers.
2. Use `PARAMETER_GUIDE.md` to understand tags and interactions.
3. Select a workflow from `templates/`, not a single universal INCAR.
4. Consult `SYSTEM_DOI_INDEX.md` first to identify the actual material/chemical system, calculation stages, and system-specific DOI status.
5. Consult `EVIDENCE.md` for what is directly supported by a source and what is reconstructed. `FILE_DOI_INDEX.md` is a secondary task/file reference.
   `literature/records.json` stores verified paper-system-task parameters; `literature/candidates.json` is discovery-only.
6. Fill every `{{PLACEHOLDER}}`; never send a template with placeholders to VASP.
7. Run `scripts/check_incar.sh INCAR` for basic static checks.
8. Run `scripts/test_library.sh` after changing the catalog or examples.

The literature layer currently contains one verified method/system record and four quarantined paper-system candidates. Candidate metadata is intentionally excluded from automatic INCAR generation until the relevant computational-details/SI text is inspected.

## Scope

The initial set covers molecular and periodic geometry optimization, 1D/2D low-dimensional systems, slab adsorption, defects, accurate static energies, two-step DOS/band structures, collinear/noncollinear magnetism, SOC, DFT+U, hybrid-functional single points, climbing-image NEB, vibrational frequencies, and NVT ab-initio molecular dynamics. `index.json` is the machine-readable routing index; `materials/` contains concrete Si, Fe, NiO, MoS2, graphene, and TiO2 profiles.

## Meaning of "validated"

`source-supported` means the method and key settings are documented in a peer-reviewed article/SI or an official VASP/VTST example. `workflow-tested` means the tag combination follows a published and established workflow. Neither means numerically converged for a new composition, cell, pseudopotential set, VASP version, or target observable.

The actual calculation must pass energy/force, cutoff, k-point, cell-size, spin-state, and model-specific convergence checks. Always inspect the interpreted settings in `OUTCAR`.
