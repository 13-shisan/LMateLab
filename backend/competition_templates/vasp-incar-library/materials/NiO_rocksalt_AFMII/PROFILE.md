# Rocksalt NiO: AFM-II correlated oxide

- Use a cell capable of alternating ferromagnetic (111) Ni planes; confirm atom ordering before assigning signed moments.
- POTCAR order example `Ni O`; use `ISPIN=2`, `ISYM=0`, and alternating initial Ni moments (a common start is magnitude 2 mu_B), O initially 0.
- Use `07_dftu_relax` with `LDAUL=2 -1`, `LDAUJ=0 0`, and a cited `LDAUU` for Ni. A frequently encountered Dudarev starting value is `Ueff=5.3 eV`, but it is not universal and must be tied to the PAW set, functional, oxidation environment, and target observable.
- Use `LMAXMIX=4`, `LASPH=.TRUE.`, and converge the AFM cell's 3D k mesh.
- Compare AFM-II against other plausible magnetic orders. Report local moments, gap, structure, U convention, and sensitivity.
