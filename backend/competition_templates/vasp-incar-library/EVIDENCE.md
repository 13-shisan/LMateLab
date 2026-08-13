# Evidence and provenance

## Evidence levels

- **A - explicit input**: a source publishes an actual input or an official worked example.
- **B - explicit methods**: article/SI states the physical method and key numerical settings, but not a complete INCAR.
- **C - reconstructed workflow**: remaining tags are conservative implementation choices based on official VASP guidance; they must not be attributed verbatim to the paper.

## Sources inspected and used

| ID | Source | Relevant system/workflow | Evidence used here |
|---|---|---|---|
| VASP-INCAR | VASP Wiki, `INCAR`, accessed 2026-08-13, https://www.vasp.at/wiki/index.php/INCAR | General | A: syntax, defaults policy, worked relaxation example, and explicit warning to verify parsed settings in OUTCAR. |
| VASP-TAGS | VASP Wiki tag pages linked from the INCAR category, https://www.vasp.at/wiki/index.php/Category:INCAR_tag | General | A: tag semantics and version-sensitive behavior. |
| VTST-NEB | Henkelman group VTST tools documentation, https://theory.cm.utexas.edu/vtsttools/neb.html | Minimum-energy paths | A/C: directory workflow and NEB/CI-NEB control tags; VTST build/version is required. |
| CI-NEB | G. Henkelman, B. P. Uberuaga, H. Jonsson, J. Chem. Phys. 113, 9901 (2000), DOI: 10.1063/1.1329672 | Climbing-image NEB method | B: physical method, not a universal VASP input. |
| NEB | G. Henkelman and H. Jonsson, J. Chem. Phys. 113, 9978 (2000), DOI: 10.1063/1.1323224 | Improved tangent NEB | B: physical method. |
| VDW-D3 | S. Grimme et al., J. Chem. Phys. 132, 154104 (2010), DOI: 10.1063/1.3382344 | D3 dispersion | B: correction method; VASP `IVDW` mapping must be checked against VASP version. |
| D3-BJ | S. Grimme et al., J. Comput. Chem. 32, 1456 (2011), DOI: 10.1002/jcc.21759 | D3(BJ) damping | B: correction method. |
| DUDAR | S. L. Dudarev et al., Phys. Rev. B 57, 1505 (1998), DOI: 10.1103/PhysRevB.57.1505 | Rotationally invariant DFT+U | B: `Ueff=U-J` convention; no transferable U values. |
| HSE | J. Heyd, G. E. Scuseria, M. Ernzerhof, J. Chem. Phys. 118, 8207 (2003), DOI: 10.1063/1.1564060; erratum DOI: 10.1063/1.2204597 | Screened hybrid functional | B: HSE framework; implementation tags checked against VASP documentation. |
| SCAN | J. Sun, A. Ruzsinszky, J. P. Perdew, Phys. Rev. Lett. 115, 036402 (2015), DOI: 10.1103/PhysRevLett.115.036402 | SCAN meta-GGA | B: parent functional definition; not direct evidence for the r2SCAN template. |
| R2SCAN | J. W. Furness et al., J. Phys. Chem. Lett. 11, 8208 (2020), DOI: 10.1021/acs.jpclett.0c02405 | r2SCAN meta-GGA | B: r2SCAN method; VASP numerical recipe remains C. |
| VASPSOL | K. Mathew et al., J. Chem. Phys. 140, 084106 (2014), DOI: 10.1063/1.4865107 | Implicit solvent for molecules/surfaces | B: model basis; actual solvation tags depend on installed VASPsol/VASP version and are intentionally not hard-coded in initial templates. |

## What was and was not obtained

The in-app browser reached the official VASP Wiki and its current INCAR page. General search engines were unavailable in the current browser session due connection resets, so this initial release does **not** claim exhaustive paper/SI harvesting and does not label reconstructed full INCARs as verbatim supplementary files. DOI records above are stable bibliographic anchors already tied to the implemented methods.

For each future paper ingestion, add a record containing title, DOI, main-text URL, SI URL/local file, VASP version, system, task, exact quoted method passage with page number, explicit tag/value mapping, inferred tags, and unresolved ambiguities. Do not upgrade B/C evidence to A without an actual input deck.

See `FILE_DOI_INDEX.md` for the direct mapping from every INCAR file to its calculation purpose, prerequisite, outputs, DOI, and evidence level.
