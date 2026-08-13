# Anatase TiO2: 3D oxide parent for bulk/surface work

- Anatase bulk baseline; POTCAR order example `Ti O`. Confirm whether `Ti` or `Ti_pv` is selected and reconverge `ENCUT`.
- Stoichiometric bulk PBE baseline: `01_bulk_relax`, normally `ISPIN=1`, `ISMEAR=0`, `SIGMA=0.05`, converged 3D mesh.
- Oxygen vacancies/Ti3+ polarons require `16_defect_relax`, spin polarization, symmetry breaking, supercell/image convergence, and several localized initial states.
- A Ti-d Dudarev +U branch uses `LDAUL=2 -1`; do not insert a universal U. Values around 3-5 eV occur in the literature for different objectives and implementations and can change localization, gap, and energetics.
- Surface calculations switch to `02_slab_adsorption_relax`, `ISIF=2`, slab/vacuum/thickness convergence, termination-specific stoichiometry, and optional dipole correction for asymmetric slabs.
