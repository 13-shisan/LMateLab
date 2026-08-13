# INCAR file, calculation purpose, and DOI index

This table answers three separate questions: what a file calculates, what must exist before it runs, and whether its settings come from a DOI-bearing method paper. A DOI in this table supports the **method**, not every numerical value in the INCAR. `VASP-INCAR`, `VASP-TAGS`, and `VTST-NEB` are documentation source IDs defined in `EVIDENCE.md` and do not have journal DOIs.

## Generic templates

| INCAR file | Calculation performed | Main result/output | Prerequisite | Source IDs / DOI | Evidence |
|---|---|---|---|---|---|
| `templates/01_bulk_relax.INCAR` | 3D bulk ionic and cell relaxation | Relaxed `CONTCAR`, energy, forces, stress | POSCAR/POTCAR/KPOINTS; spin decision | VASP-INCAR, VASP-TAGS; no DOI | C, official-workflow reconstruction |
| `templates/02_slab_adsorption_relax.INCAR` | Adsorbate/slab ionic relaxation at fixed cell | Relaxed adsorption geometry and precursor energies | Converged slab/vacuum; selective dynamics | VASP-TAGS; no DOI | C |
| `templates/03_molecule_relax.INCAR` | Isolated molecule ionic relaxation | Relaxed molecular geometry | Converged box/vacuum and spin state | VASP-TAGS; no DOI | C |
| `templates/04_static_energy.INCAR` | Self-consistent high-accuracy single point | Comparable total energy, `CHGCAR`, `AECCAR*` | Relaxed geometry; compatible restart files | VASP-TAGS; no DOI | C |
| `templates/05_dos.INCAR` | Fixed-density DOS/PDOS | DOSCAR and projected states | Compatible converged `CHGCAR`; dense uniform KPOINTS | VASP-TAGS; no DOI | C |
| `templates/06_band_nscf.INCAR` | Fixed-density line-path band calculation | Eigenvalues along high-symmetry path | Output of template 13; line-mode KPOINTS | VASP-TAGS; no DOI | C |
| `templates/07_dftu_relax.INCAR` | Collinear DFT+U structural relaxation | Correlated-state geometry, energy, moments | Cited U/J and magnetic order | DUDAR; `10.1103/PhysRevB.57.1505` | B method + C VASP recipe |
| `templates/08_hse06_static.INCAR` | HSE06 screened-hybrid single point | Hybrid energy/eigenstates | Converged geometry; hybrid-compatible k workflow | HSE; `10.1063/1.1564060`, erratum `10.1063/1.2204597` | B method + C VASP recipe |
| `templates/09_cineb.INCAR` | Climbing-image nudged elastic band | Minimum-energy path and saddle candidate | Relaxed endpoints, interpolated images, VTST-compatible build | NEB `10.1063/1.1323224`; CI-NEB `10.1063/1.1329672`; VTST-NEB | A documentation + B method + C numeric choices |
| `templates/10_vibrations_finite_difference.INCAR` | Finite-difference Hessian/frequencies | Normal modes and imaginary-mode count | Tightly relaxed stationary geometry | VASP-TAGS; no DOI | C |
| `templates/11_aimd_nvt.INCAR` | Born-Oppenheimer NVT AIMD | Temperature-controlled trajectory | Equilibrated structure; timestep/thermostat tests | VASP-TAGS; no single DOI assigned | C |
| `templates/12_r2scan_static.INCAR` | r2SCAN meta-GGA single point | r2SCAN total energy/eigenstates | Compatible VASP version/PAWs and starting density | r2SCAN: Furness et al., `10.1021/acs.jpclett.0c02405` | B method + C VASP recipe |
| `templates/13_band_scf.INCAR` | Uniform-mesh self-consistent precursor for bands | Ground-state `CHGCAR` and `WAVECAR` | Relaxed cell; converged uniform KPOINTS | VASP-TAGS; no DOI | C |
| `templates/14_soc_static.INCAR` | Noncollinear spin-orbit single point | SOC energy, spinor eigenstates, moments | Scalar-relativistic ground state; vector moments | VASP-TAGS; no DOI | C |
| `templates/15_noncollinear_relax.INCAR` | Noncollinear magnetic ionic relaxation | Geometry and noncollinear moments | Proposed magnetic structure; vector `MAGMOM` | VASP-TAGS; no DOI | C |
| `templates/16_defect_relax.INCAR` | Neutral or explicitly charged defect relaxation | Defect geometry, energy, charge/moment data | Converged supercell; charge/correction plan | VASP-TAGS; no DOI | C; formation-energy correction not included |
| `templates/17_2d_material_relax.INCAR` | 2D layer relaxation with fixed vacuum | Relaxed layer geometry | Converged vacuum and in-plane k mesh | VASP-TAGS; no DOI | C |
| `templates/18_1d_material_relax.INCAR` | 1D wire/chain relaxation with fixed vacuum | Relaxed wire/chain geometry | Converged transverse vacuum and axial k mesh | VASP-TAGS; no DOI | C |

## Concrete example files

| INCAR file | Exact example calculation | DOI status | Important limitation |
|---|---|---|---|
| `materials/Si_diamond/INCAR.relax.example` | PBE relaxation of diamond Si bulk | No paper DOI assigned; reconstructed example | `ENCUT=520` and k mesh must match/converge for the selected Si PAW. |
| `materials/Si_diamond/INCAR.band_scf.example` | Uniform-mesh SCF density for Si bands | No paper DOI assigned | Requires a suitable regular mesh and relaxed cell. |
| `materials/Si_diamond/INCAR.band_nscf.example` | Fixed-density Si line-path bands | No paper DOI assigned | Requires compatible SCF `CHGCAR`; path depends on cell convention. |
| `materials/Fe_bcc_FM/INCAR.relax.example` | Spin-PBE relaxation of FM bcc Fe | No paper DOI assigned | Initial `2.2 mu_B` is a seed, not a guaranteed final moment. |
| `materials/NiO_rocksalt_AFMII/INCAR.relax.example` | PBE+Dudarev-U relaxation of AFM-II NiO | DFT+U method DOI `10.1103/PhysRevB.57.1505`; no NiO SI provenance | `Ueff=5.3 eV` is an example choice and atom order is assumed explicitly. |
| `materials/MoS2_monolayer/INCAR.relax.example` | PBE ionic relaxation of monolayer 2H-MoS2 | No paper DOI assigned | Fixed vacuum; no dispersion or SOC in this relaxation file. |
| `materials/graphene/INCAR.relax.example` | PBE ionic relaxation of pristine graphene | No paper DOI assigned | Semimetal k sampling must resolve the K point. |
| `materials/TiO2_anatase/INCAR.relax_pbe.example` | PBE bulk relaxation of anatase TiO2 | No paper DOI assigned | No +U in this file; Ti/Ti_pv choice changes convergence. |

## Workflow chains

- **Relaxation -> final energy:** `01/02/03/07/15/16/17/18` -> `04`.
- **Band structure:** relaxation -> `13_band_scf` on a uniform mesh -> `06_band_nscf` on a standardized line path.
- **DOS:** relaxation -> `04` or other converged SCF -> `05` with a denser uniform mesh.
- **Reaction barrier:** relax initial/final states -> `09_cineb` -> relax/check saddle -> `10_vibrations`.
- **Magnetic anisotropy/SOC:** converge magnetic structure without SOC -> `14_soc_static` for consistently varied spin axes.
