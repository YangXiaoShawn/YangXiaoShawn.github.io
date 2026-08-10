"""Generate provenance-aware research and portfolio reports from pipeline artifacts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import polars as pl

SYNTHETIC_NOTICE = (
    "> **Synthetic fixture demonstration.** All dates, releases, observations, forecasts, "
    "metrics, and model rankings below validate software behavior only. They are not empirical "
    "findings about the U.S. economy."
)


def _fmt(value: object, digits: int = 3) -> str:
    if value is None:
        return "not available"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "not available"
        return f"{value:.{digits}f}"
    return str(value)


def _markdown_table(frame: pl.DataFrame, columns: list[str] | None = None) -> str:
    if frame.is_empty():
        return "No rows were produced."
    selected = columns or frame.columns
    selected = [column for column in selected if column in frame.columns]
    rows = frame.select(selected).to_dicts()
    header = "| " + " | ".join(selected) + " |"
    divider = "| " + " | ".join("---" for _ in selected) + " |"
    body = [
        "| " + " | ".join(_fmt(row.get(column)) for column in selected) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def render_policy_brief(news: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    """Render a one-page brief without inventing unsupported economic interpretation."""

    fixture_label = str(manifest.get("fixture_label", "unknown"))
    notice = SYNTHETIC_NOTICE if fixture_label == "synthetic_fixture" else ""
    contributions = news.get("contributions", [])
    contribution_lines = []
    for contribution in contributions:
        name = contribution.get("feature", "unknown feature")
        value = _fmt(contribution.get("contribution"))
        contribution_lines.append(f"- `{name}`: {value} thousand jobs (model units)")
    if not contribution_lines:
        contribution_lines.append("- No defensible contribution decomposition was available.")

    interval = news.get("interval") or {}
    lower = _fmt(interval.get("lower"))
    upper = _fmt(interval.get("upper"))
    exactness = news.get("attribution_label", "approximate")
    previous = _fmt(news.get("previous_nowcast"))
    updated = _fmt(news.get("updated_nowcast"))
    revision = _fmt(news.get("forecast_revision"))
    release_name = news.get("release_name", "Configured synthetic release")
    released_at = news.get("release_ts", "not recorded")

    return f"""# Sample Policy Brief

{notice}

**Release:** {release_name}

**Release time:** {released_at}

**Target:** {manifest.get('target', 'configured target')}

**Horizon:** {manifest.get('horizon', 0)}

**Data mode:** {news.get('data_mode', 'vintage_aware')}

**Attribution:** {exactness}

## What changed

The fixed model's nowcast moved from **{previous}** to **{updated}** thousand jobs, a revision of **{revision}**. The displayed interval is **[{lower}, {upper}]**. This is a simulated information update, not a report about a real release.

## Contribution to the update

{chr(10).join(contribution_lines)}

The contribution accounting is labeled **{exactness}**. An exact label means a frozen linear model was scored before and after the release and its feature contributions sum to the prediction change within numerical tolerance. It does not imply causal identification.

## Assessment and uncertainty

The synthetic update demonstrates whether the release moved the configured employment signal up or down and by how much inside this fitted model. Sampling error, model instability, target revisions, missing predictors, and the deliberately artificial data-generating process limit interpretation.

## Historical context

No real historical analogue is asserted. Fixture-derived percentiles or episodes are not evidence about past U.S. business cycles.

## What would change the conclusion

- A subsequent release that materially reverses the changed input.
- A target revision large enough to alter the training relationship.
- A wider real-time sample in which the update is not stable across forecast origins.
- A genuine-vintage replication using data with documented usage permission and verified release timing.

## Risks to interpretation

This brief describes model arithmetic, not a causal policy shock. It does not predict monetary-policy or investment decisions. Date-only source releases require an explicit timing convention; this fixture uses exact synthetic timestamps.
"""


def write_policy_brief(
    news: Mapping[str, Any], manifest: Mapping[str, Any], destination: Path
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_policy_brief(news, manifest))
    return destination


def _technical_report(manifest: Mapping[str, Any], metrics: pl.DataFrame) -> str:
    return f"""# Technical Report

{SYNTHETIC_NOTICE}

## System delivered

The repository implements a typed, configuration-driven pipeline for canonical vintages, explicit release events, arbitrary historical as-of reconstruction, audited mixed-frequency features, expanding-window forecasts, revision analysis, release-news attribution, Parquet/DuckDB persistence, automated reporting, and a local dashboard.

The sample target is `{manifest.get('target', 'unknown')}` at horizon `{manifest.get('horizon', 0)}`. The fixed evaluation vintage is `{manifest.get('latest_evaluation_date', 'not recorded')}` and the run identifier is `{manifest.get('run_id', 'not recorded')}`.

## Information-set discipline

For vintage-aware rows, a raw observation is eligible only when its availability timestamp is no later than the forecast origin. Selection occurs before transformations, aggregations, or missing-value handling. Each derived feature records the maximum availability timestamp of its inputs, and validation rejects any value later than its origin.

The counterfactual revised matrix preserves the historical eligibility mask and substitutes only the value at the fixed evaluation vintage. This isolates revisions from the separate error of adding observation periods that had not yet been released.

## Models and evaluation

Preprocessing is fitted within each expanding fold. Hyperparameters are fixed in the sample configuration; the final evaluation period is not used for tuning. Prediction intervals use prior out-of-sample residuals and remain missing until the minimum residual history exists.

{_markdown_table(metrics, ['model_id', 'data_mode', 'n_forecasts', 'rmse', 'mae', 'bias', 'directional_accuracy', 'directional_accuracy_meaningful', 'interval_coverage'])}

Directional accuracy is omitted when the evaluation target never changes sign, because a constant positive-sign forecast would make that statistic uninformative.

## Reproducibility

The run manifest records the fixture label, configuration hash, input hash, series list, sample dates, target, horizon, seed, and package versions. `make reproduce-sample` recreates every generated analytical artifact from the deterministic source fixture.

## Scope

These results validate the research-engineering path. Genuine empirical conclusions require authorized data, verified historical timestamps, and a substantially larger real-time sample.
"""


def _leakage_report(
    metrics: pl.DataFrame,
    revisions: pl.DataFrame,
    target_revision_summary: pl.DataFrame,
) -> str:
    comparison_rows: list[dict[str, object]] = []
    if {"model_id", "data_mode", "rmse", "mae"}.issubset(metrics.columns):
        for model in metrics["model_id"].unique().sort().to_list():
            subset = metrics.filter(pl.col("model_id") == model)
            vintage = subset.filter(pl.col("data_mode") == "vintage_aware")
            revised = subset.filter(pl.col("data_mode") == "latest_values_same_eligibility_mask")
            if vintage.height and revised.height:
                comparison_rows.append(
                    {
                        "model_id": model,
                        "vintage_rmse": vintage["rmse"][0],
                        "revised_rmse": revised["rmse"][0],
                        "rmse_difference": revised["rmse"][0] - vintage["rmse"][0],
                        "vintage_mae": vintage["mae"][0],
                        "revised_mae": revised["mae"][0],
                    }
                )
    comparison = pl.DataFrame(comparison_rows) if comparison_rows else pl.DataFrame()
    return f"""# Vintage Leakage Study

{SYNTHETIC_NOTICE}

## Question

How much does a backtest change when later-revised values replace the vintages actually available at each historical origin, holding the eligible series/observation mask fixed?

## Design

`vintage_aware` features use the most recent eligible vintage at each origin. `latest_values_same_eligibility_mask` first determines those same eligible cells and then substitutes their fixed-evaluation-vintage values. Targets and feature modes remain explicitly labeled. This is narrower and more interpretable than a naive revised-data matrix that also admits observations published after the forecast origin.

The multi-target workflow additionally materializes that wider matrix under the explicit
name `naive_latest_revised`. Its audit counts cells first available after the historical
origin, so the result measures intentional release-timing leakage and is never a valid
real-time backtest. The fixed-mask experiment remains the primary value-revision
comparison.

## Fixture result

{_markdown_table(comparison)}

The sign and size of these synthetic differences are properties of the deterministic fixture. They demonstrate that the comparison is measurable and reproducible; they do not estimate real-world leakage or prove that one model class is superior.

## Revision distribution

{_markdown_table(revisions, ['series_id', 'revision_count', 'mean_revision', 'mean_abs_revision', 'max_abs_revision'])}

## Forecast error and target revision

For each vintage-aware forecast, the same prediction is scored once against the synthetic first release and once against the fixed-evaluation-vintage target. The difference therefore isolates target revision from model re-estimation or feature revision.

{_markdown_table(target_revision_summary, ['model_id', 'n_forecasts', 'mae_first_release', 'mae_latest_revised', 'mean_target_revision', 'mean_abs_target_revision', 'mean_change_in_absolute_error_due_to_target_revision'])}

## Required empirical follow-up

Repeat the fixed-mask comparison on authorized genuine vintages, freeze the evaluation vintage, verify source release timestamps, and evaluate whether rankings persist across horizons and economic regimes.
"""


def _model_report(
    metrics: pl.DataFrame,
    dm: pl.DataFrame,
    grouped: pl.DataFrame,
    stability: pl.DataFrame,
) -> str:
    return f"""# Model Comparison

{SYNTHETIC_NOTICE}

## Expanding-window results

{_markdown_table(metrics)}

## Diebold–Mariano-style comparisons

{_markdown_table(dm)}

## Performance by configured regime and horizon

The fixture regimes are deterministic calendar partitions for exercising grouped evaluation; they are not identified economic regimes.

{_markdown_table(grouped)}

## Stability across vintage modes

{_markdown_table(stability)}

Simple baselines and advanced estimators use the same origins and eligibility masks. The sample keeps hyperparameters fixed and fits imputers/scalers only inside each training fold. Any comparison with an insufficient loss history is reported as such rather than assigned a significance claim.

No model-ranking claim should be carried outside this synthetic fixture.
"""


def _limitations_report(manifest: Mapping[str, Any]) -> str:
    return f"""# Methodology and Limitations

{SYNTHETIC_NOTICE}

## Target and timing

The configured target is `{manifest.get('target', 'unknown')}`. The vertical slice nowcasts a reference month before its initial synthetic release. A first-release payroll change uses both the current and prior PAYEMS levels from the same post-release information set so that a concurrent revision to the prior month is treated correctly.

## Vintage selection

Real-time intervals and explicit availability timestamps are separate fields. A date-only external source would be available under the conservative end-of-day convention documented in configuration; this fixture carries exact UTC timestamps. Missing or retracted latest rows remain missing and do not resurrect an earlier vintage.

## Mixed frequencies and ragged edges

Weekly and daily features aggregate only observations released by the origin. Monthly indicators can be stale because publication lags differ. Transformations are applied after vintage resolution. Feature lineage stores the latest input observation and maximum input availability time.

## Forecast evaluation

Training feature rows preserve their own historical origins. Training targets must have been released by the test origin. Expanding windows are monotone, preprocessing is fold-local, interval residuals are strictly prior out-of-sample errors, and the final evaluation block is not used for tuning.

## Attribution

Frozen linear-model attribution exactly decomposes the mechanical prediction change into coefficient-times-feature changes. It is not causal attribution. Tree updates use an order-dependent replacement calculation and are labeled approximate.

## Data and legal limitations

No genuine FRED/ALFRED content is bundled or downloaded. Current FRED service terms appear to conflict with the requested caching/database and software-development workflow, while an older official API terms page differs. Live access is disabled behind an authorization gate pending clarification. Original-provider data may have separate licenses and release-time conventions.

## Statistical limitations

Synthetic fixtures cannot support estimates of real forecast accuracy, business-cycle regime performance, interval calibration, revision distributions, or policy implications. Formal comparisons are guarded for small samples. GDP/inflation expansion, intraday releases, and robust empirical regime analysis remain follow-up work.
"""


def _portfolio_files(manifest: Mapping[str, Any]) -> dict[str, str]:
    target = manifest.get("target", "monthly payroll change")
    return {
        "interview_story.md": f"""# Interview Story

## Macroeconomic research

I built the project around a deceptively simple question: what did a forecaster actually know at the time? For `{target}`, I represented every observation with its release availability and revision interval, then reconstructed each forecast origin rather than using today's cleaned history.

## Econometric discipline

The central comparison holds the historical eligibility mask fixed and swaps only later revisions. That separates revision leakage from publication-lag leakage. Fold-local preprocessing, expanding windows, first-release versus final targets, guarded statistical tests, and explicit uncertainty keep the exercise honest.

## Research engineering

The workflow runs offline from deterministic fixtures through Parquet and DuckDB to models, metrics, attribution, a policy brief, reports, and a Streamlit dashboard. Strict tests fail if any derived feature carries a post-origin availability timestamp. Live FRED access is implemented but gated because current terms require clarification.

## Honest outcome

The current numbers are synthetic demonstrations, so I would present the supported result as a production and research-design achievement—not as evidence about actual payroll predictability. The next empirical step is to source authorized genuine vintages and rerun the frozen design.
""",
        "resume_bullets.md": """# Resume Bullets

- Built a Python 3.12 real-time macro nowcasting engine using Polars, Parquet, DuckDB, scikit-learn, and statsmodels, with arbitrary historical information-set reconstruction across monthly, weekly, and daily data.
- Designed strict vintage-leakage controls that propagate source availability through transformed features and automatically reject post-origin inputs.
- Implemented expanding-window benchmark and regularized/tree model evaluation with fold-local preprocessing, residual intervals, revision analysis, and guarded forecast-comparison tests.
- Automated reproducibility manifests, exact linear news attribution, one-page policy briefs, research reports, and a local monitoring dashboard.
- Separated synthetic validation from empirical claims and gated live API ingestion after identifying a material terms-of-use conflict with persistent caching/model development.
""",
        "ten_minute_presentation_outline.md": """# Ten-Minute Presentation Outline

## 0:00–1:00 — The research trap

Today's revised macro history was not the history available to yesterday's forecaster. Show the central question and the synthetic-data warning.

## 1:00–2:30 — Information-set data model

Explain observation date, release availability, vintage interval, and forecast origin. Demonstrate one observation changing across vintages.

## 2:30–4:00 — No-future-information invariant

Walk through snapshot selection, post-selection transforms, mixed-frequency ragged edges, and lineage validation.

## 4:00–5:30 — Fair leakage comparison

Contrast vintage-aware features with latest values on the same historical eligibility mask. Explain why admitting future periods answers a different question.

## 5:30–7:00 — Model ladder and evaluation

Show historical mean, no-change, AR, bridge, Elastic Net, and gradient boosting on identical expanding folds. Emphasize fold-local preprocessing and prior-residual intervals.

## 7:00–8:15 — Release update and attribution

Show the pre/post nowcast, exact frozen-linear contribution identity, uncertainty, and non-causal interpretation.

## 8:15–9:15 — Production workflow

Trace configuration → fixture adapter → Parquet/DuckDB → audited matrices → forecasts → reports/dashboard. Mention offline tests and run hashes.

## 9:15–10:00 — What is supported and next

The system behavior is validated; the fixture is not economic evidence. Next: authorized genuine vintages, verified release timing, inflation/GDP targets, and larger-sample regime/stability analysis.
""",
    }


def write_required_reports(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    metrics: pl.DataFrame,
    revisions: pl.DataFrame,
    dm: pl.DataFrame,
    grouped: pl.DataFrame,
    stability: pl.DataFrame,
    target_revision_summary: pl.DataFrame,
    news: Mapping[str, Any],
) -> list[Path]:
    """Write every required report and portfolio artifact from structured outputs."""

    reports = root / "reports"
    portfolio = root / "portfolio"
    reports.mkdir(parents=True, exist_ok=True)
    portfolio.mkdir(parents=True, exist_ok=True)
    contents = {
        reports / "technical_report.md": _technical_report(manifest, metrics),
        reports / "vintage_leakage_study.md": _leakage_report(
            metrics,
            revisions,
            target_revision_summary,
        ),
        reports / "model_comparison.md": _model_report(
            metrics,
            dm,
            grouped,
            stability,
        ),
        reports / "sample_policy_brief.md": render_policy_brief(news, manifest),
        reports / "methodology_and_limitations.md": _limitations_report(manifest),
    }
    contents.update({portfolio / name: text for name, text in _portfolio_files(manifest).items()})
    for path, text in contents.items():
        path.write_text(text)
    return list(contents)
