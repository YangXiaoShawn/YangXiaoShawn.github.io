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

## Required release record

Every new data source must record origin, retrieval date, geographic and temporal coverage, transformations, units, frequency, schema, checksum, license, and publication class.
