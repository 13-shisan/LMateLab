# Graphene: 2D semimetal

- Primitive hexagonal monolayer with converged vacuum; POTCAR order `C`.
- Relax with `17_2d_material_relax`, normally `ISPIN=1`, `ISMEAR=0`, `SIGMA=0.05`; use `kx ky 1` sampling.
- Preserve/test the honeycomb symmetry unless modeling strain, defects, adsorption, or symmetry breaking.
- Bands require SCF then NSCF path for the actual standardized hexagonal cell, including K to resolve the Dirac crossing. A mesh missing K can misrepresent the Fermi-level behavior.
- Defective/zigzag-edge graphene can be magnetic: switch to `ISPIN=2`, construct multiple initial moment patterns, enlarge the cell, and converge image separation.
