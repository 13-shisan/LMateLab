# What each template changes and why

| Template | Key changes from a semilocal static calculation | Intended result |
|---|---|---|
| `01_bulk_relax` | `IBRION=2`, `NSW>0`, negative `EDIFFG`, `ISIF=3` | Relax ions and all cell degrees for a 3D bulk crystal. |
| `02_slab_adsorption_relax` | `ISIF=2`, `ISYM=0`, optional `LDIPOL/IDIPOL` | Relax adsorbate and free slab atoms without collapsing vacuum; correct asymmetric-slab dipole if justified. |
| `03_molecule_relax` | Gamma-only context, Gaussian smearing, `IDIPOL=4`, tighter forces | Relax an isolated molecule in a converged vacuum box. |
| `04_static_energy` | No ion motion, tighter SCF, restart density/waves, write analysis files | Comparable final total energy on a converged geometry. |
| `05_dos` | `ICHARG=11`, dense DOS grid, `LORBIT=11` | Non-self-consistent projected DOS from a compatible converged `CHGCAR`. |
| `06_band_nscf` | `ICHARG=11`, line-mode KPOINTS, extra `NBANDS` | Eigenvalues along a reciprocal-space path; not a new ground-state density. |
| `07_dftu_relax` | Dudarev +U arrays, spin, `LASPH`, larger `LMAXMIX` | Localized d/f correction with auditable U convention and magnetic state. |
| `08_hse06_static` | Exact exchange, HSE screening, damped algorithm | Screened-hybrid single point; algorithm and k mesh need separate convergence. |
| `09_cineb` | Image chain, springs, climb, VTST optimizer, symmetry off | Minimum-energy path and saddle candidate; validate the highest image with frequencies. |
| `10_vibrations` | Very tight SCF, finite displacements, small `POTIM` | Hessian/frequencies for selected movable atoms; converged geometry is prerequisite. |
| `11_aimd_nvt` | MD integrator, thermostat, timestep, temperature, looser SCF | Canonical-ensemble trajectory after timestep, thermostat, and finite-size checks. |
| `12_r2scan_static` | `METAGGA=R2SCAN`, kinetic-energy-density mixing, strict grids | r2SCAN energy from a compatible starting density; check VASP version and PAWs. |
| `13_band_scf` | Uniform converged mesh, write `CHGCAR/WAVECAR`, extra bands | Ground-state density prerequisite for the line-path calculation. |
| `14_soc_static` | Noncollinear spinors, `LSORBIT`, vector moments, symmetry off | SOC energy/eigenstates or a building block for magnetic anisotropy. |
| `15_noncollinear_relax` | Vector moments and symmetry off | Relax a noncollinear magnetic state without silently imposing collinearity. |
| `16_defect_relax` | Spin/symmetry breaking, optional audited charge, analysis density | Localize and relax a defect; formation energy corrections are separate. |
| `17_2d_material_relax` | Fixed vacuum, `kz=1` context, optional normal dipole | Relax a 2D layer without vacuum-vector artifacts. |
| `18_1d_material_relax` | Fixed vacuum directions, symmetry off | Relax a wire/chain with only one periodic k-sampled direction. |

## Cross-cutting modules to add only when justified

- Dispersion: add the version-correct `IVDW` or a complete nonlocal vdW functional recipe to every compared state. D3 and D3(BJ) are not interchangeable.
- Solvation: use only tags supported by the installed VASP/VASPsol version; document dielectric, ionic strength, cavity/surface parameters, and reference state.
- Charged systems: `NELECT` alone is not a finite-size correction. Document neutralizing background, electrostatic correction, vacuum/cell convergence, and chemical/electrode potential convention.
- SOC/noncollinear: create a separate workflow with `LSORBIT`, vector `MAGMOM`, `SAXIS`, compatible symmetry, and sufficient bands; do not append `LSORBIT` blindly.
- Selective dynamics belongs in POSCAR, not INCAR. Verify constrained atoms before interpreting forces or frequencies.
