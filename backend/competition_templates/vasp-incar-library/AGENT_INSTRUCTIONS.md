# Agent instructions for adaptive INCAR generation

## Required input facts

Before writing an INCAR, determine or explicitly mark unknown:

- VASP version and available licenses/features.
- Task: relaxation, static energy, adsorption energy, DOS, bands, barrier, vibration, AIMD, dielectric response, etc.
- Boundary condition: isolated molecule, 3D bulk, 2D slab, 1D wire, charged cell.
- Elements, approximate oxidation states, magnetic atoms, expected metal/semiconductor/insulator behavior.
- POTCAR family and `ENMAX` values, including whether hard potentials are needed.
- Exchange-correlation functional and corrections (dispersion, +U, hybrid, SOC, solvation).
- Cell size, vacuum direction, symmetry, fixed atoms, k-point mesh and computing resources.
- Accuracy target and which quantities will be compared.

If a scientifically material choice is unknown, do not silently invent it. Emit a conservative draft, label the assumption, and request confirmation.

## Selection flow

1. Choose the base workflow by observable and boundary condition.
   Search `index.json` first. If a matching concrete profile exists, read `SYSTEM_DOI_INDEX.md`, its `PROFILE.md`, and the generic template; profile constraints override generic defaults. Never present a method DOI as system-specific evidence.
   Search `literature/records.json` for matching system/task evidence. Never use `literature/candidates.json` to populate parameters.
2. Choose electronic occupation:
   - metal or uncertain gap during relaxation: `ISMEAR = 1`, `SIGMA = 0.1` (test alternatives);
   - molecule/semiconductor relaxation: `ISMEAR = 0`, `SIGMA = 0.05`;
   - accurate final energy/DOS: tetrahedron only with a suitable regular k mesh; otherwise Gaussian with small sigma.
3. Choose spin before relaxation. Use `ISPIN = 2` and chemically informed `MAGMOM` for radicals, open-shell molecules, transition metals, lanthanides, defects, and uncertain magnetic solids. Test competing states.
4. Set `ENCUT` from the actual POTCAR set, normally at least `1.3 * max(ENMAX)` for robust force/stress comparisons, then converge it.
5. For cell relaxation use `ISIF = 3` only for genuine 3D bulk. Do not relax a slab vacuum vector with `ISIF = 3`; normally use `ISIF = 2`.
6. Add only justified physics modules. Do not mix DFT+U, dispersion, hybrids, SOC, dipole correction, or solvation into only one side of an energy difference.
7. Preserve numerical consistency across compared states: functional, POTCARs, `ENCUT`, k-point density, smearing strategy, spin treatment, slab thickness, vacuum, dipole settings, and precision.
8. For a property run, start from a converged geometry and charge density as required by the selected template.

## Mandatory output from the agent

Return:

- the INCAR without unresolved placeholders;
- a short assumptions block outside the INCAR;
- a list of changed key tags and the physical reason for each;
- tag-level provenance: `explicit_source`, `official_default`, `template_choice`, or `system_assumption`;
- matching KPOINTS guidance and POTCAR order;
- prerequisite files (`WAVECAR`, `CHGCAR`, NEB image directories, etc.);
- at least one convergence plan;
- warnings for uncertain magnetism, +U values, charged slabs, hybrid/SOC compatibility, or unsupported VASP version.

## Hard safety rules

- Never claim a template is converged for a new system.
- Never infer `LDAUU`, `LDAUL`, `LDAUJ`, `MAGMOM`, `NELECT`, or `NUPDOWN` solely from element names.
- Never use `ICHARG = 11` unless a compatible converged `CHGCAR` exists.
- Never use `ISTART = 1` unless a compatible `WAVECAR` exists.
- Never compare energies from inconsistent Hamiltonians or pseudopotentials.
- Do not enable `LASPH = .FALSE.` for +U, meta-GGA, hybrid, or non-spherical transition-metal chemistry.
- Avoid `LREAL = Auto` for small/high-accuracy final calculations; use `.FALSE.` unless memory/cost justifies approximation and it is tested.
- A negative `EDIFFG` is a force threshold in eV/Angstrom; a positive value is an energy criterion.
- Verify all interpreted tags in `OUTCAR`, electronic/ionic convergence, forces, stress, magnetization, and warnings.
