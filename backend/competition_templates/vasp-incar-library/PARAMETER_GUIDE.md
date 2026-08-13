# INCAR parameter guide for chemistry workflows

This is a practical semantic guide to the tags used by this library. Defaults and feature behavior can change with VASP version; the VASP Wiki page for each tag is authoritative.

## Identity, restart, and electronic initialization

| Tag | Meaning | Decision rule / pitfall |
|---|---|---|
| `SYSTEM` | Human-readable job label | No physics effect. Include structure, method, and stage. |
| `ISTART` | Wavefunction start mode | `0` atomic orbitals; `1` compatible `WAVECAR`. Cell changes can make restarts unsafe. |
| `ICHARG` | Initial/fixed charge density | `2` atomic superposition; `1` read `CHGCAR`; `11` fixed density for non-SCF bands/DOS. `ICHARG=11` requires compatible `CHGCAR`. |
| `INIWAV` | Initial orbitals | Usually leave default. Rarely a useful tuning knob. |
| `NELM` | Maximum electronic steps | Raising it does not cure bad mixing, wrong magnetism, or unsuitable algorithms. |
| `NELMIN` | Minimum electronic steps | Useful in MD/ionic relaxation for stable forces; do not overuse. |

## Basis, accuracy, and projection

| Tag | Meaning | Decision rule / pitfall |
|---|---|---|
| `ENCUT` | Plane-wave kinetic-energy cutoff (eV) | Derive from actual POTCAR `ENMAX`; converge the observable. Keep identical in energy comparisons. |
| `PREC` | FFT-grid and numerical precision preset | `Accurate` for production energies/forces. It is not a replacement for converging `ENCUT`. |
| `ENAUG` | Augmentation-charge cutoff | Usually default; can matter for stress/response with hard PAWs. |
| `ADDGRID` | Extra support grid | Often reduces force noise, but verify for the chosen functional/version. |
| `LREAL` | Real-space PAW projection | `.FALSE.` most reproducible for small/accurate jobs; `Auto` can save cost for large cells after testing. |
| `LASPH` | Non-spherical PAW one-center contributions | Use `.TRUE.` for transition-metal chemistry, +U, meta-GGA, and hybrids. |
| `LMAXMIX` | Angular momentum retained in charge mixing/CHGCAR | Often `4` for d and `6` for f systems, especially +U and `ICHARG=11` workflows. |
| `ROPT` | Real-space projector optimization precision | Only relevant with real-space projection; do not tune casually. |

## Electronic minimization and convergence

| Tag | Meaning | Decision rule / pitfall |
|---|---|---|
| `ALGO` | Electronic minimization algorithm family | `Normal` is robust; `Fast` is common for semilocal DFT; hybrids often use `Damped`/`All` depending on version and system. |
| `IALGO` | Low-level electronic algorithm selector | Prefer `ALGO` unless reproducing a documented workflow. |
| `EDIFF` | Electronic total-energy stopping threshold (eV) | Typical production `1E-6`; tighter for phonons/response. Force quality can require tighter SCF. |
| `NELMDL` | Delayed electronic steps | Specialized stabilization; not a general fix. |
| `TIME` | Trial time step in some electronic algorithms | Important for damped hybrid minimization; must be tested. |
| `AMIX`, `BMIX`, `AMIX_MAG`, `BMIX_MAG` | Charge/magnetic mixing | Diagnose oscillation first; system-specific, especially magnetic metals. |
| `MAXMIX` | Mixer history retained | Can help repeated ionic/MD steps, with memory tradeoff. |

## Occupations and integration

| Tag | Meaning | Decision rule / pitfall |
|---|---|---|
| `ISMEAR` | Occupation/integration method | `1/2` Methfessel-Paxton for metals during relaxation; `0` Gaussian; `-1` Fermi; `-5` tetrahedron with Blöchl corrections for suitable final regular-mesh calculations. |
| `SIGMA` | Smearing width (eV) | Check entropy contribution and convergence. Do not use a large metallic sigma for final molecular energies. |
| `EFERMI` | Fermi-level convention | Usually leave default; relevant to reproducible band/DOS reporting in newer versions. |

## Ionic motion, cell, and stress

| Tag | Meaning | Decision rule / pitfall |
|---|---|---|
| `IBRION` | Ionic update method | `2` conjugate gradient relaxation; `1` quasi-Newton; `3` damped dynamics; `5/6` finite-difference phonons; `-1` no ionic update. |
| `NSW` | Maximum ionic steps | `0` static. Reaching `NSW` is not convergence. |
| `EDIFFG` | Ionic stopping criterion | Negative means max force threshold (eV/Angstrom); positive means energy change. |
| `POTIM` | Ionic step scale / MD time step (fs) | Meaning depends on `IBRION`; reduce for unstable relaxations or light atoms in MD. |
| `ISIF` | Which positions/cell degrees and stress are optimized | `2` ions only; `3` ions+shape+volume for 3D bulk. Slab vacuum normally must stay fixed. |
| `ISYM` | Symmetry handling | `0` limited symmetry, `-1` off. Disable when symmetry would constrain NEB, defects, fields, SOC, or intended distortion. |
| `SYMPREC` | Symmetry tolerance | A too-loose value can impose false symmetry; a too-tight one can lose useful symmetry. |

## Spin, magnetism, SOC, and constraints

| Tag | Meaning | Decision rule / pitfall |
|---|---|---|
| `ISPIN` | Collinear spin polarization | `2` for open-shell/uncertain magnetic systems. Compare plausible magnetic states. |
| `MAGMOM` | Initial local magnetic moments | Initialization and symmetry breaking, not guaranteed final oxidation/spin state. Order follows POSCAR species/atoms. |
| `NUPDOWN` | Fix total spin polarization | Use only for a deliberately constrained spin state. |
| `LNONCOLLINEAR` | Noncollinear magnetism | Changes `MAGMOM` to 3 components/ion; check version-specific syntax. |
| `LSORBIT` | Spin-orbit coupling | Requires noncollinear treatment; usually symmetry and k-point considerations change. |
| `SAXIS` | Spin quantization axis | Relevant to SOC/noncollinear calculations. |
| `LAMBDA`, `M_CONSTR`, `I_CONSTRAINED_M` | Constrained local moments | Advanced constrained-magnetism workflow; requires careful penalty convergence. |

## DFT+U and exchange-correlation

| Tag | Meaning | Decision rule / pitfall |
|---|---|---|
| `GGA` | GGA selection | Must match the intended functional and POTCAR compatibility. |
| `METAGGA` | Meta-GGA selection (e.g. SCAN/r2SCAN) | Requires appropriate precision, `LASPH`, dense grids, and version checks. |
| `LDAU` | Enable on-site correction | Values are method-, element-, oxidation-, and PAW-dependent. Cite the chosen convention. |
| `LDAUTYPE` | +U formulation | Type `2` is Dudarev `Ueff=U-J`; other types are not interchangeable. |
| `LDAUL` | Corrected orbital per species | `2` d, `3` f, `-1` none. Must align with POTCAR species order. |
| `LDAUU`, `LDAUJ` | U and J per species (eV) | Never guess. Preserve the published convention and test sensitivity. |
| `LDAUPRINT` | +U diagnostic output | Useful for auditing occupation matrices. |
| `LHFCALC` | Enable hybrid exchange | Expensive; requires compatible algorithm/k-point workflow. |
| `AEXX` | Fraction of exact exchange | HSE06 commonly `0.25`; do not change without defining the functional. |
| `HFSCREEN` | Range-separation screening (1/Angstrom) | HSE06 commonly `0.2`; PBE0 has no screening. |
| `PRECFOCK` | Fock-exchange precision | `Fast` is common; converge when accurate energy differences matter. |

## Dispersion, dipoles, fields, and charge

| Tag | Meaning | Decision rule / pitfall |
|---|---|---|
| `IVDW` | Empirical/charge-dependent dispersion method | Integer maps to a specific model and VASP version. Cite it and use consistently. |
| `LUSE_VDW`, `AGGAC`, `PARAM1`, `PARAM2` | Nonlocal vdW-DF family controls | Functional-specific combination; never mix recipe fragments. |
| `LDIPOL` | Apply dipole correction | Useful for asymmetric slabs/isolated polar systems; can slow convergence. |
| `IDIPOL` | Dipole direction | `1/2/3` lattice direction, `4` molecule. Ensure the vacuum direction matches. |
| `DIPOL` | Reference center in direct coordinates | Usually center of charge/slab; inspect planar potential. |
| `EFIELD` | External electric field parameter | Boundary-condition sensitive; not equivalent to constant electrode potential. |
| `NELECT` | Total electron count override | Creates a charged periodic cell with compensating background; finite-size/electrostatic corrections are required. |

## Outputs and electronic properties

| Tag | Meaning | Decision rule / pitfall |
|---|---|---|
| `LWAVE`, `LCHARG` | Write `WAVECAR` / `CHGCAR` | Enable only when downstream restart/property calculations need them. |
| `LORBIT` | Projected DOS/band output controls | `11` is common with PAW; projection depends on PAW spheres and is not a unique charge partition. |
| `NEDOS` | DOS energy-grid count | Increase for smooth DOS; does not add physical resolution beyond k sampling/broadening. |
| `EMIN`, `EMAX` | DOS energy window | Set only when a deliberate window is needed. |
| `NBANDS` | Number of bands | Increase for unoccupied states, hybrids, response, GW, or difficult parallelization. |
| `LPARD`, `IBAND`, `EINT` | Partial charge density selection | Property-specific; beware band indexing and spin. |
| `LAECHG` | All-electron core+valence density output | Needed for common Bader workflows (`AECCAR0/2`). |
| `LELF` | Electron localization function | Produces ELFCAR; converged density/grid required. |

## NEB, vibrations, and molecular dynamics

| Tag | Meaning | Decision rule / pitfall |
|---|---|---|
| `IMAGES` | Number of intermediate NEB images | Endpoints excluded; matching atom order and good interpolation are essential. |
| `SPRING` | NEB spring constant | Negative values invoke common improved tangent behavior in VTST-style workflows. |
| `LCLIMB` | Climbing image | Usually enable after a reasonable band/path exists; VTST patch/version dependent. |
| `ICHAIN`, `IOPT` | VTST chain optimizer controls | Not standard in every VASP build; record VTST version. |
| `NFREE` | Displacements per degree for finite differences | Used with phonon `IBRION`; more displacements cost more. |
| `TEBEG`, `TEEND` | Initial/final MD temperature | Thermostat- and ensemble-dependent. |
| `MDALGO` | MD/thermostat algorithm | Version-dependent; define ensemble and thermostat parameters together. |
| `SMASS` | Nose mass or thermostat selector | Meaning depends on MD setup and VASP version. |
| `LANGEVIN_GAMMA` | Per-species Langevin friction | Units and count must match species; use with the matching `MDALGO`. |

## Parallel performance (not transferable physics)

`NCORE`, `NPAR`, `KPAR`, `NSIM`, and `LPLANE` depend on hardware, VASP build, k points, bands, and cell size. They must not be copied from a paper as scientific parameters. Keep them in scheduler/site profiles, not chemistry templates, unless a deployment target is known.
