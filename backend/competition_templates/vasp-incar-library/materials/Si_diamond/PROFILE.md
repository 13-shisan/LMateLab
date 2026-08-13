# Diamond Si: 3D semiconductor and bands

- Primitive or conventional diamond cell; PBE PAW, POTCAR order `Si`.
- Start `ENCUT=520 eV` only after confirming this exceeds the chosen POTCAR requirement; converge it.
- Relax with `01_bulk_relax`, `ISPIN=1`, `ISMEAR=0`, `SIGMA=0.05`.
- Use a converged uniform 3D mesh (a primitive-cell starting test may be 8x8x8 or denser).
- Run `13_band_scf`, then `06_band_nscf` along a path generated for the final standardized diamond cell. Do not assume the conventional-cell path applies to a primitive cell.
- PBE underestimates the Si band gap; HSE06 or a higher-level method changes the observable, not merely numerical convergence.
