# Monolayer 2H-MoS2: 2D semiconductor

- Hexagonal 2H monolayer with at least a converged vacuum separation; POTCAR order example `Mo S`.
- Relax with `17_2d_material_relax`, `ISPIN=1`, `ISMEAR=0`, `SIGMA=0.05`, and `kx ky 1` mesh.
- `ISIF=2` keeps the chosen vacuum fixed. To optimize in-plane lattice constants, perform controlled volume/area scans or a constrained-cell workflow; do not allow unphysical vacuum stress to drive the cell.
- For an isolated symmetric monolayer, dipole correction is normally unnecessary; enable it for asymmetric functionalization/fields after checking the planar potential.
- Interlayer/bilayer calculations require a consistently selected dispersion method. A D3(BJ) branch can use the version-correct `IVDW=12`, but this defines a different method and must be cited and converged.
- Band edges near K are SOC-sensitive. Run the scalar-relativistic SCF/bands baseline, then `14_soc_static` or an SOC band workflow with adequate bands and a documented reciprocal path.
