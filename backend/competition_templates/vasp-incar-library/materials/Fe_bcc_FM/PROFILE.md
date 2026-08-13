# bcc Fe: ferromagnetic metal

- bcc Fe bulk; spin-polarized PBE PAW, POTCAR order `Fe`.
- Start each Fe near `MAGMOM=2.2` as an initialization, then inspect the converged moment.
- Relax with `01_bulk_relax`, `ISPIN=2`, `ISMEAR=1`, `SIGMA=0.1`; use a dense 3D mesh and converge stress/energy.
- For final energies, test tetrahedron (`ISMEAR=-5`) on a suitable regular mesh and compare against small-smearing extrapolation.
- Competing nonmagnetic/low-spin starts are diagnostic; a single FM initialization is not proof of the ground state.
- SOC and magnetic anisotropy require `14_soc_static` with much tighter convergence.
