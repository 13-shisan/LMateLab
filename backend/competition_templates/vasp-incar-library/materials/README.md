# Concrete material profiles

These profiles are executable-style starting configurations demonstrating how the generic templates change for recognizable systems. They are separated from generic templates because lattice, phase, PAW release, U value, magnetic order, slab termination, and target accuracy are material-specific.

| Profile | Dimension | Physics demonstrated | Status |
|---|---:|---|---|
| `Si_diamond` | 3D | semiconductor relaxation + two-step bands | established PBE workflow starting point |
| `Fe_bcc_FM` | 3D | ferromagnetic metal | established spin-PBE workflow starting point |
| `NiO_rocksalt_AFMII` | 3D | AFM correlated insulator, Dudarev +U | literature-style example; U is explicitly non-universal |
| `MoS2_monolayer` | 2D | semiconductor, dispersion/SOC branches | established 2D workflow starting point |
| `graphene` | 2D | semimetal and Dirac band path | established 2D workflow starting point |
| `TiO2_anatase` | 3D/surface parent | oxide relaxation and optional Ti-d +U branch | PBE baseline; U branch requires a cited target-specific choice |

Each directory contains a `PROFILE.md` with geometry, KPOINTS, POTCAR, and convergence requirements. INCAR snippets intentionally refer back to templates when a branch needs unresolved scientific choices.

Files named `INCAR.*.example` contain no placeholders and are static-checkable examples under the exact assumptions in their profile. They are not proof that `ENCUT=520`, a given moment, or a U value is converged for a different POTCAR/cell.
