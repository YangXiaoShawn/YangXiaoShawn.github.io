# Repository Instructions

## Mission

Build a reproducible real-time macroeconomic nowcasting system that reconstructs the information set available at each historical forecast origin. The core comparison is a valid vintage-aware backtest versus a clearly labeled latest-revised-data backtest.

## Non-negotiable research rules

- Never allow an observation whose `availability_date` is later than the requested `as_of_date` into a feature matrix.
- Never substitute latest-revised values for historical vintages unless the output is explicitly labeled `latest_revised`.
- Preserve raw source fields and provenance. Derived values must record the transformation and source vintage.
- Never fabricate releases, vintages, metrics, forecasts, or policy conclusions.
- Fixture-backed outputs must be labeled `synthetic_fixture`; they demonstrate behavior, not empirical findings about the economy.
- When exact intraday release timing is unavailable, use the documented end-of-day convention and do not claim pre-release availability.
- Target definitions must state units and transformation (for example, `persons_change_mom`, `percent_change_mom`, or `percent_change_qoq_saar`).
- Any attribution that is not an exact additive decomposition must be labeled approximate.

## Architecture and storage

- Put production logic in the typed `src/macro_nowcast` package, never only in notebooks.
- Use configuration-driven series definitions under `config/`.
- Canonical vintage rows include series ID, observation date, real-time start/end, availability date, value, units, frequency, seasonal adjustment, transformation, download timestamp, and source metadata.
- Use Parquet for durable columnar artifacts and DuckDB for local analytical queries. Keep fixture data small.
- Keep raw downloads immutable. Write derived datasets to separate directories.
- Live FRED/ALFRED access is optional, requires `FRED_API_KEY` plus an explicit authorization gate, and must remain disabled by default under the currently published FRED terms. Unit tests must use committed synthetic fixtures and work offline. Do not persist API-derived content without documented permission.

## Implementation order

1. Maintain `docs/PROJECT_PLAN.md`, `docs/DECISION_LOG.md`, and `STATUS.md`.
2. Complete the monthly payroll vertical slice before expanding targets or model families.
3. Add strict as-of and leakage tests before reporting model results.
4. Compare transparent baselines with advanced models using the same forecast origins.
5. Generate reports and the dashboard only from versioned pipeline outputs.

## Quality workflow

- Use Python 3.12, type annotations, pytest, and ruff.
- After each major phase, run the narrow tests first and then the full suite.
- Prefer deterministic expanding-window evaluation; never tune on the final evaluation period.
- Each chart or table must identify data mode, series/target, vintage/as-of rule, horizon, and sample period.
- Update `STATUS.md` after material work, including commands run, validated behavior, limitations, and next milestones.
- Record consequential assumptions or design changes in `docs/DECISION_LOG.md`.

## Common commands

The supported workflow is exposed through `make setup`, `make download-sample`, `make build-vintages`, `make validate-asof`, `make backtest`, `make test`, `make reproduce-sample`, `make reproduce-multitarget`, `make policy-brief`, `make report`, and `make dashboard`.
