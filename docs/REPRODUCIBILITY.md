# Reproducibility

## Entry points

- CasualLab: `make reproduce`
- Macroeconomics: `python -m macro_nowcast.pipeline`

## Environment and data

- Each project retains a `pyproject.toml` and project-specific setup notes.
- Compact public copies include fixtures and small samples for smoke tests.
- Full research content is versioned in the Hugging Face Dataset.
- Local `.venv`, `.pytest_cache`, `.ruff_cache`, `__pycache__`, and operating-system metadata are never research inputs and are excluded from releases.

## Evidence standard

A result is treated as reproduced only when the source, sample period, configuration, command, output manifest, and validation result are recorded. Missing benchmark evidence is described as a limitation rather than replaced with a simulated claim.

## Refreshes

Network-backed source updates must run in an authorized environment. Updated outputs should record source retrieval time, dataset revision, transformation steps, and checksums before the site or Space presents them as current results.
