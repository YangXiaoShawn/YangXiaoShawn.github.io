# Data Governance

## Publication classes

- `PUBLIC_OK`: redistribution is confirmed and the full asset may be published.
- `PUBLIC_DERIVED_ONLY`: only documented derived outputs and samples may be published.
- `METADATA_ONLY`: publish citations, metadata, and source links only.
- `PRIVATE`: do not publish.
- `RIGHTS_UNKNOWN`: hold new raw assets until terms are reviewed.

## Routing policy

GitHub stores code, metadata, tests, schemas, documentation, and compact fixtures. Hugging Face stores versioned research data and public outputs. The Space reads from the Dataset and does not duplicate persistent data.

## Current projects

CasualLab and Macroeconomics include project-owned code and public examples. Raw third-party assets retain `RIGHTS_UNKNOWN` where redistribution terms have not been documented. Their presence in an earlier full snapshot does not convert them to a new license.

RealEstate is `PUBLIC_OK` for project-owned source, tests, documentation, synthetic fixtures, and aggregate reports, and `PRIVATE` for registered Freddie Mac loan-level records and loan-granular derivatives. Public packaging is restricted to tracked files and excludes `data/raw/`, `data/interim/`, `data/processed/`, `data/cache/`, and `outputs/`.

Tariff Incidence is `PUBLIC_OK` for tracked source and narrative reports, with large raw, staged, normalized, analytical, and parquet result files excluded.

Microstructure is `PUBLIC_OK` for its canonical Git-tracked MIT source, tests, configuration, protocols, and documentation. Exchange observations and locally generated research state are `METADATA_ONLY`: `data/raw/`, normalized and derived tables, model states, M8/L2 authorities, and `artifacts/runs/` are excluded from GitHub's publication mirror and the Hugging Face Dataset. A single machine-generated, low-dimensional scenario summary is `PUBLIC_DERIVED_ONLY` for the website and Space. It carries the nonconfirmatory evidence label, checksum provenance, and reference-only disclaimer, and excludes events, ledgers, models, local paths, and run files.

## Required release record

Every new data source must record origin, retrieval date, geographic and temporal coverage, transformations, units, frequency, schema, checksum, license, and publication class.
