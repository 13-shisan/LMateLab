# Literature search and ingestion protocol

## Search scope

Search across publisher main text and SI (including institutional-access pages), Crossref/DOI metadata, Europe PMC/PMC, arXiv, ChemRxiv, institutional repositories, Materials Cloud, NOMAD, Materials Project input provenance, and author-linked GitHub/Zenodo/Figshare records. A publisher page is preferred for bibliographic identity; SI or an input repository is preferred for actual settings.

Representative query blocks combine:

- code: `VASP`, `Vienna ab initio simulation package`;
- input evidence: `INCAR`, `supporting information`, `computational details`, `energy cutoff`, `k-point`, `EDIFF`, `ISMEAR`, `LDAU`, `IVDW`, `NEB`;
- system classes: magnetic oxide, 3D bulk, monolayer, surface adsorption, defect, catalyst, molecule, MOF, battery electrode;
- tasks: relaxation, adsorption energy, band structure, DOS, phonon, AIMD, transition state, SOC.

## Institutional-access handling

- Campus-network access broadens eligible sources but does not lower evidence requirements.
- Record `institutional_access=true` only when the full main text or SI was actually readable, not merely when a DOI page loaded.
- Cloudflare/CAPTCHA/login/paywall pages are access blockers, not evidence. Do not bypass them.
- Save bibliographic metadata and a pending reason when a source is blocked; never transcribe search snippets as calculation parameters.

## Extraction checklist

For every paper-system-stage, extract when disclosed:

- VASP version, PAW/POTCAR flavor and element order;
- functional, dispersion, +U convention/values, hybrid, SOC, solvation;
- `ENCUT`, precision/grids, SCF/force criteria, smearing;
- spin order and initial moments;
- ionic/cell degrees of freedom and constraints;
- k mesh or reciprocal spacing and band path;
- supercell, slab layers, vacuum, defect charge, adsorbate coverage;
- restart/property workflow and output being calculated.

Use the exact evidence location (main text section, SI page/table, repository path). Do not mark inferred VASP tags as explicit.

## Promotion rule

`candidate_pending_fulltext` -> `verified_key_parameters` only after at least one calculation-setting statement is inspected in main text/SI. Promote to `full_incar` only when the actual input is available. Any generated completed INCAR remains a separate derived artifact with tag-level provenance.
