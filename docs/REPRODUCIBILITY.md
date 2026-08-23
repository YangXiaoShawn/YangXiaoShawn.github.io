# Reproducibility

## Entry points

- CasualLab: `make reproduce`
- Macroeconomics: `python -m macro_nowcast.pipeline`
- Mortgage Rate Lock-In: `make reproduce-sample`
- Tariff Incidence: `make reproduce-sample`
- Microstructure: `make reproduce-sample`

## Environment and data

- Each project retains a `pyproject.toml` and project-specific setup notes.
- Compact public copies include fixtures and small samples for smoke tests.
- Publishable research content is versioned in the Hugging Face Dataset. Microstructure's Dataset mirror intentionally contains code and documentation only, not local market observations or generated runs. The website and Space additionally contain one machine-generated, checksum-verified, low-dimensional exploratory summary; they do not contain its source run bundle.
- Local `.venv`, `.pytest_cache`, `.ruff_cache`, `__pycache__`, and operating-system metadata are never research inputs and are excluded from releases.

## Evidence standard

A result is treated as reproduced only when the source, sample period, configuration, command, output manifest, and validation result are recorded. Missing benchmark evidence is described as a limitation rather than replaced with a simulated claim.

## Refreshes

Network-backed source updates must run in an authorized environment. Updated outputs should record source retrieval time, dataset revision, transformation steps, and checksums before the site or Space presents them as current results.
