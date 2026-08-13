# KPOINTS and band-workflow guide

INCAR cannot define a complete k-point workflow by itself. The agent must generate KPOINTS together with INCAR.

## Dimensionality rules

| System | Relaxation / SCF mesh | Vacuum direction |
|---|---|---|
| 3D bulk | Gamma-centered or Monkhorst-Pack mesh converged in all axes | None |
| 2D slab | Dense in-plane mesh, exactly 1 point normal to slab | Commonly `kx ky 1` for vacuum along c |
| 1D wire | Dense along periodic axis, 1 in both vacuum axes | E.g. `1 1 kz` for wire along c |
| Isolated molecule | Gamma only | All three axes nonperiodic by cell-size approximation |

Use a reciprocal-space resolution criterion (for example a target k-point spacing) rather than copying integer meshes between different cells. Converge the target observable.

## Two-step band calculation

1. Run a self-consistent calculation on a converged uniform mesh using `13_band_scf.INCAR`; save `CHGCAR` and usually `WAVECAR`.
2. Run `06_band_nscf.INCAR` with `ICHARG=11` and a line-mode KPOINTS path appropriate to the relaxed primitive cell and its actual Bravais lattice.

Do not guess high-symmetry labels from a chemical formula. Determine the standardized reciprocal path from the final cell (e.g. SeeK-path/spglib convention), record the convention, and preserve the mapping if a supercell is unfolded.

For hybrid functionals, a simple line-only KPOINTS file may omit the occupied-manifold integration needed for exact exchange. Use a documented zero-weight path plus the regular mesh or a supported hybrid band workflow, and verify against the current VASP documentation.
