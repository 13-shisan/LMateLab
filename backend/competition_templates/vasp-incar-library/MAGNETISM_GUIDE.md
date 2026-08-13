# Magnetic-system workflow

## Collinear FM/AFM screening

1. Build chemically and crystallographically valid FM, ferrimagnetic, and symmetry-distinct AFM initial states. AFM may require a supercell.
2. Use identical structures/numerics initially, `ISPIN=2`, and signed `MAGMOM` values in exact POSCAR atom order.
3. Relax each state without symmetry if symmetry would map opposite spin sites (`ISYM=0` is a conservative start).
4. Compare converged energies only after checking final local moments, total magnetization, electronic convergence, and whether states collapsed to the same solution.
5. Re-relax the lowest plausible states and converge k mesh, cutoff, and (if present) U.

`MAGMOM` is an initial condition and symmetry-breaking handle, not a measured moment. Transition-metal oxidation state, ligand field, and high-/low-spin state matter more than the element alone.

## Noncollinear and SOC

Use `15_noncollinear_relax` for noncollinear order without SOC and `14_soc_static` for a SOC single point. In noncollinear mode, `MAGMOM` has three components per ion. For magnetic anisotropy energy, compare consistent converged calculations with different `SAXIS`/moment direction at much tighter numerical settings; energy differences can be micro-eV to meV scale.

SOC calculations commonly require more bands, disabled/reduced symmetry, fully relativistic PAW support, and careful restart semantics. Never combine collinear `ISPIN=2` recipes blindly with `LNONCOLLINEAR`.

## DFT+U

Use `07_dftu_relax` only with a cited U/J method and values. `LDAUTYPE=2` implements Dudarev's effective U convention. Arrays follow POSCAR/POTCAR species order, not atomic number. Test magnetic order and U sensitivity together because they are coupled.
