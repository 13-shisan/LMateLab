# System-centered DOI and INCAR index

This is the primary provenance index for answering: **which chemical/material system was calculated, what calculation was performed, and which paper/SI DOI supports that system setup?**

## Current concrete systems

| System ID | Actual system represented | INCAR files | Calculations represented | System-specific article/SI DOI | Provenance status |
|---|---|---|---|---|---|
| `Si_diamond` | Elemental Si in the 3D diamond structure | `INCAR.relax.example`, `INCAR.band_scf.example`, `INCAR.band_nscf.example` | PBE bulk relaxation; uniform-mesh SCF; line-path band structure | **Not yet assigned** | Reconstructed standard example, not copied from a paper SI |
| `Fe_bcc_FM` | Elemental Fe in 3D body-centered-cubic ferromagnetic order | `INCAR.relax.example` | Spin-polarized PBE bulk/cell relaxation | **Not yet assigned** | Reconstructed standard example; initial moment is a seed |
| `NiO_rocksalt_AFMII` | Rocksalt NiO with type-II antiferromagnetic ordering | `INCAR.relax.example` | Spin-polarized PBE+Dudarev-U bulk relaxation | `10.1103/PhysRevB.57.1505` | Paper is explicitly about the DFT+U method and NiO-related application; the local full INCAR is still reconstructed, not a verbatim SI file |
| `MoS2_monolayer` | Isolated single layer of 2H-MoS2 with vacuum normal to c | `INCAR.relax.example` | PBE fixed-vacuum ionic relaxation; profile describes later band/SOC branches | **Not yet assigned** | Reconstructed 2D workflow, not copied from a paper SI |
| `graphene` | Pristine 2D graphene primitive layer | `INCAR.relax.example` | PBE fixed-vacuum ionic relaxation; profile describes Dirac-band workflow | **Not yet assigned** | Reconstructed 2D workflow, not copied from a paper SI |
| `TiO2_anatase` | Stoichiometric 3D anatase TiO2 bulk; profile also routes surfaces and oxygen vacancies | `INCAR.relax_pbe.example` | PBE bulk/cell relaxation | **Not yet assigned** | Reconstructed oxide baseline, not copied from a paper SI |

## Interpretation

- A DOI in the table must refer to a paper that actually calculates the named system, not merely a general VASP or density-functional method paper.
- `Not yet assigned` means no main-text/SI calculation record has yet been ingested and checked for that system. It does not mean relevant literature does not exist.
- A system DOI alone is insufficient for `verbatim_si`: the SI must expose enough information to map the actual VASP version, POTCARs, functional, cutoff, k mesh, spin, U/dispersion/SOC choices, relaxation thresholds, and cell model.
- Each future ingested system should receive its own directory containing `PROFILE.md`, DOI/main-text/SI metadata, exact quoted method passages, and separate INCAR files for every calculation stage.

## Required future record format

```yaml
system_id: journal_year_shortname
chemical_system: exact composition, phase, surface/defect/adsorbate, charge, spin
doi: 10.xxxx/xxxxx
article_url: ...
si_url_or_local_file: ...
vasp_version: ...
potcar_release_and_order: ...
workflow:
  - stage: relaxation
    incar_file: ...
    evidence: verbatim_si | explicit_methods | reconstructed
  - stage: scf
    incar_file: ...
    evidence: ...
  - stage: bands_or_dos_or_neb
    incar_file: ...
    evidence: ...
unresolved: [...]
```
