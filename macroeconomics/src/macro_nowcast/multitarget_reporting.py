"""Honest, structured reporting for completed synthetic multi-target runs."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import polars as pl

from macro_nowcast.target_config import load_target_config

SYNTHETIC_NOTICE = (
    "> **SYNTHETIC FIXTURE DEMONSTRATION — NO EMPIRICAL FINDINGS.** "
    "All observations, releases, forecasts, revisions, metrics, and comparisons below "
    "validate software behavior only; they are not evidence about the economy or model "
    "superiority."
)


def _fmt(value: object, *, digits: int = 4) -> str:
    if value is None:
        return "not available"
    if isinstance(value, float):
        return f"{value:.{digits}f}" if math.isfinite(value) else "not available"
    return str(value)


def _markdown_table(frame: pl.DataFrame, columns: list[str]) -> str:
    selected = [column for column in columns if column in frame.columns]
    if frame.is_empty() or not selected:
        return "No rows were produced."
    rows = frame.select(selected).to_dicts()
    header = "| " + " | ".join(selected) + " |"
    divider = "| " + " | ".join("---" for _ in selected) + " |"
    body = []
    for row in rows:
        values = [_fmt(row.get(column)).replace("|", "\\|") for column in selected]
        body.append("| " + " | ".join(values) + " |")
    return "\n".join([header, divider, *body])


def _target_ids(*frames: pl.DataFrame) -> list[str]:
    discovered: set[str] = set()
    for frame in frames:
        if "target_series_id" in frame.columns:
            discovered.update(str(value) for value in frame["target_series_id"].drop_nulls())
    order = ("PAYEMS", "CPILFESL", "GDPC1")
    return [value for value in order if value in discovered] + sorted(
        discovered.difference(order)
    )


def _manifest_entries(manifest: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    for key in ("target_definitions", "targets", "target_configs"):
        raw = manifest.get(key)
        if isinstance(raw, Mapping):
            result = {}
            for series_id, value in raw.items():
                if isinstance(value, Mapping):
                    result[str(series_id)] = value
            if result:
                return result
        if isinstance(raw, list):
            result = {}
            for value in raw:
                if isinstance(value, Mapping):
                    series_id = value.get("target_series_id", value.get("series_id"))
                    if isinstance(series_id, str):
                        result[series_id] = value
            if result:
                return result
    return {}


def _target_contracts(
    manifest: Mapping[str, object],
    metrics: pl.DataFrame,
    revisions: pl.DataFrame,
) -> pl.DataFrame:
    configured = load_target_config()
    entries = _manifest_entries(manifest)
    discovered = set(_target_ids(metrics, revisions)) or set(configured.by_series)
    rows: list[dict[str, object]] = []
    for series_id in ("PAYEMS", "CPILFESL", "GDPC1"):
        if series_id not in discovered:
            continue
        target = configured.get(series_id)
        entry = entries.get(series_id, {})
        target_metrics = (
            metrics.filter(pl.col("target_series_id") == series_id)
            if "target_series_id" in metrics.columns
            else pl.DataFrame()
        )
        rows.append(
            {
                "target_series_id": series_id,
                "target_name": entry.get("target_name", entry.get("name", target.name)),
                "frequency": entry.get(
                    "target_frequency", entry.get("frequency", target.frequency)
                ),
                "units": entry.get("target_units", entry.get("units", target.units)),
                "formula": entry.get(
                    "target_formula", entry.get("formula", target.formula)
                ),
                "sample_start": entry.get(
                    "evaluation_start", entry.get("sample_start", target.evaluation_start)
                ),
                "sample_end": entry.get(
                    "evaluation_end", entry.get("sample_end", target.evaluation_end)
                ),
                "minimum_train_periods": entry.get(
                    "minimum_train_periods", target.minimum_train_periods
                ),
                "metric_rows": target_metrics.height,
            }
        )
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def dm_diagnostic_summary(dm_comparisons: pl.DataFrame) -> str:
    """Summarize validity/status without turning a test statistic into a ranking."""

    if dm_comparisons.is_empty():
        return "No DM comparison rows were produced; no model-ranking inference is available."
    if "valid" not in dm_comparisons.columns:
        return (
            "DM rows do not carry the required validity flag; they are not interpreted as "
            "evidence of model superiority."
        )
    valid = dm_comparisons.filter(pl.col("valid").fill_null(False))
    invalid = dm_comparisons.filter(pl.col("valid").fill_null(False).not_())
    parts = [
        f"{valid.height} comparison(s) are marked valid only as synthetic diagnostics; "
        "they do not establish model superiority."
    ]
    if invalid.height:
        status_columns = [
            column
            for column in ("target_series_id", "status", "reason", "n_obs")
            if column in invalid.columns
        ]
        details = []
        for row in invalid.select(status_columns).unique().sort(status_columns).to_dicts():
            details.append(", ".join(f"{key}={_fmt(value)}" for key, value in row.items()))
        parts.append(
            f"{invalid.height} comparison(s) are invalid and remain descriptive: "
            + "; ".join(details)
            + "."
        )
    if (
        "target_series_id" in invalid.columns
        and invalid.filter(pl.col("target_series_id") == "GDPC1").height
    ):
        parts.append(
            "Quarterly GDP has a small evaluation sample; insufficient-observation status is "
            "reported honestly rather than converted into a significance claim."
        )
    return " ".join(parts)


def render_multitarget_report(
    manifest: Mapping[str, object],
    metrics: pl.DataFrame,
    dm_comparisons: pl.DataFrame,
    revision_summary: pl.DataFrame,
    *,
    model_stability: pl.DataFrame | None = None,
    leakage_audit: pl.DataFrame | None = None,
) -> str:
    """Render a concise multi-target comparison and limitations report."""

    fixture_label = manifest.get("fixture_label", "unknown")
    empirical_supported = manifest.get("empirical_findings_supported", False)
    contracts = _target_contracts(manifest, metrics, revision_summary)
    metric_columns = [
        "target_series_id",
        "target_name",
        "target_frequency",
        "target_units",
        "model_id",
        "data_mode",
        "feature_mode",
        "target_mode",
        "n_forecasts",
        "rmse",
        "mae",
        "bias",
        "interval_coverage",
    ]
    dm_columns = [
        "target_series_id",
        "baseline_model",
        "comparison_model",
        "statistic",
        "p_value",
        "n_obs",
        "valid",
        "status",
        "reason",
    ]
    revision_columns = [
        "target_series_id",
        "target_name",
        "model_id",
        "n_forecasts",
        "mean_target_revision",
        "mean_abs_target_revision",
        "mae_first_release",
        "mae_latest_revised",
        "mean_change_in_absolute_error_due_to_target_revision",
    ]
    contracts_table = _markdown_table(
        contracts,
        [
            "target_series_id",
            "target_name",
            "frequency",
            "units",
            "formula",
            "sample_start",
            "sample_end",
            "minimum_train_periods",
            "metric_rows",
        ],
    )
    metrics_table = _markdown_table(metrics, metric_columns)
    dm_table = _markdown_table(dm_comparisons, dm_columns)
    revision_table = _markdown_table(revision_summary, revision_columns)
    stability_table = _markdown_table(
        model_stability if model_stability is not None else pl.DataFrame(),
        [
            "target_series_id",
            "model_id",
            "comparison_mode",
            "n_aligned",
            "prediction_correlation",
            "mean_abs_prediction_difference",
            "vintage_rmse_rank",
            "counterfactual_rmse_rank",
            "rank_change",
        ],
    )
    leakage_table = _markdown_table(
        leakage_audit if leakage_audit is not None else pl.DataFrame(),
        [
            "target_series_id",
            "information_set_mode",
            "feature_cells",
            "selected_vintage_after_origin_cells",
            "first_eligibility_after_origin_cells",
            "valid_real_time_information_set",
            "research_purpose",
        ],
    )
    target_note = (
        "The formulas and units are target-specific: payroll is a monthly level "
        "difference, core CPI is a nonannualized monthly percent change, and real GDP "
        "is an exactly compounded quarter-over-quarter SAAR. They must not be pooled as "
        "though they shared units or frequency."
    )
    metrics_note = (
        "These rows are displayed without selecting a winner. Differences among models "
        "or vintage modes are deterministic properties of the synthetic fixture and do "
        "not establish forecast superiority or real-world accuracy."
    )
    revision_note = (
        "Revision rows measure how the synthetic first-release and fixed-latest targets "
        "differ. They do not estimate actual historical revision behavior."
    )
    limitations = "\n".join(
        [
            f"- This run is labeled `{fixture_label}` and supports no empirical finding.",
            "- Metrics, ranks, p-values, and revision effects cannot be generalized "
            "beyond the deterministic fixture.",
            "- Quarterly GDP has fewer forecast origins than the monthly targets; "
            "invalid or insufficient DM tests remain explicitly invalid.",
            "- Cross-target metric magnitudes are not directly comparable because "
            "formulas, frequencies, scales, and units differ.",
            "- Attribution and forecast changes are model accounting, not causal policy "
            "effects.",
            "- Genuine-vintage use requires authorized source data, verified release "
            "timing, and a frozen evaluation vintage.",
        ]
    )
    return f"""# Synthetic Multi-Target Forecast Comparison and Limitations

{SYNTHETIC_NOTICE}

## Run contract

- Artifact stage: `{manifest.get('artifact_stage', 'not recorded')}`
- Run status: `{manifest.get('status', 'not recorded')}`
- Fixture label: `{fixture_label}`
- Empirical findings supported: `{empirical_supported}`
- Timing violations: `{_fmt(manifest.get('timing_violations'))}`

## Target definitions and samples

{contracts_table}

{target_note}

## Expanding-window model diagnostics

{metrics_table}

{metrics_note}

## Revised-data leakage design

`vintage_aware` is the valid historical information set.
`latest_values_same_eligibility_mask` substitutes fixed-vintage values only for cells
already eligible at each origin. `naive_latest_revised` intentionally admits cells whose
first release occurred after the origin. The last mode is a deliberately invalid benchmark,
never a real-time backtest.

{leakage_table}

## Model stability across vintage modes

{stability_table}

Ranks and prediction differences are synthetic diagnostics. They show whether the comparison
machinery is active, not which model is preferable in real data.

## Diebold-Mariano diagnostics

{dm_diagnostic_summary(dm_comparisons)}

{dm_table}

## Target-revision diagnostics

{revision_table}

{revision_note}

## Limitations and interpretation guardrails

{limitations}
"""


def render_multitarget_policy_brief(
    news: Mapping[str, object],
    manifest: Mapping[str, object],
) -> str:
    """Render one target-specific release brief from audited pipeline output."""

    contributions = news.get("contributions")
    contribution_lines: list[str] = []
    if isinstance(contributions, list):
        for item in contributions:
            if not isinstance(item, Mapping):
                continue
            contribution_lines.append(
                "- `{}`: {} {} (feature {} → {})".format(
                    item.get("feature", "unknown"),
                    _fmt(item.get("contribution")),
                    news.get("target_units", "target units"),
                    _fmt(item.get("previous_value")),
                    _fmt(item.get("updated_value")),
                )
            )
    if not contribution_lines:
        contribution_lines.append("- No defensible additive contribution was available.")

    interval = news.get("interval")
    interval = interval if isinstance(interval, Mapping) else {}
    comparison = news.get("historical_comparison")
    comparison = comparison if isinstance(comparison, Mapping) else {}
    changed_features = news.get("changed_features")
    changed = (
        ", ".join(f"`{value}`" for value in changed_features)
        if isinstance(changed_features, list)
        else "not recorded"
    )
    return f"""# {news.get('target_series_id', 'Configured Target')} Synthetic Release Brief

{SYNTHETIC_NOTICE}

## Release and target contract

- What was released: {news.get('release_name', 'configured synthetic release')}
- Release timestamp: `{news.get('release_ts', 'not recorded')}`
- Reference period: `{news.get('release_observation_date', 'not recorded')}`
- Changed feature(s): {changed}
- Target: `{news.get('target_name', 'unknown')}` (`{news.get('target_series_id', 'unknown')}`)
- Formula: `{news.get('target_formula', 'not recorded')}`
- Frequency: `{news.get('target_frequency', 'unknown')}`
- Units: `{news.get('target_units', 'unknown')}`
- Horizon: `{news.get('horizon', 0)}`
- Information set: `{news.get('data_mode', 'vintage_aware')}`

## What changed relative to the prior information set

The frozen `{news.get('model_id', 'model')}` nowcast moved from
**{_fmt(news.get('previous_nowcast'))}** to
**{_fmt(news.get('updated_nowcast'))}**, a revision of
**{_fmt(news.get('forecast_revision'))} {news.get('target_units', 'target units')}**.
{news.get('assessment', '')}

## Contribution accounting

{chr(10).join(contribution_lines)}

Attribution is `{news.get('attribution_label', 'not recorded')}`. Exact means the same
fitted linear model was scored on the before/after feature vectors and contributions
reproduce the forecast revision within numerical tolerance. It does not imply causality.

## Forecast uncertainty

The **{_fmt(interval.get('coverage'))}** prior-residual interval is
**[{_fmt(interval.get('lower'))}, {_fmt(interval.get('upper'))}]**, based on
`{_fmt(interval.get('residual_count'))}` eligible prior residuals. A missing interval is
retained when the predeclared residual minimum is not met.

## Historical comparison

The absolute update is at percentile **{_fmt(comparison.get('percentile'))}** among
`{_fmt(comparison.get('n_comparisons'))}` prior absolute consecutive out-of-sample nowcast
movements; their median is **{_fmt(comparison.get('median_absolute_movement'))}**. This is a
fixture-only scale comparison, not a claim about real historical releases or business-cycle
analogues.

## Risks to interpretation

- Every date, value, model result, and comparison is deterministic synthetic fixture output.
- The update is mechanical model accounting, not a causal policy shock.
- Target revisions, missing predictors, ragged edges, model instability, and small samples
  can change the assessment.
- No monetary-policy, investment, or model-superiority conclusion is supported.

## What evidence would change the conclusion

- A subsequent eligible release that reverses the changed feature or forecast direction.
- A materially different first-release target or later target revision.
- Failure of the update to persist across historical origins, models, or authorized genuine
  vintages.
- Verified source timing or archive evidence that changes the reconstructed information set.

Run `{manifest.get('run_id', 'not recorded')}` supports software-validation findings only.
"""


def write_multitarget_policy_briefs(
    updates: Sequence[Mapping[str, object]],
    manifest: Mapping[str, object],
    destination: Path,
) -> list[Path]:
    """Write exactly one deterministic brief for every target release update."""

    destination.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    seen: set[str] = set()
    for news in updates:
        series_id = str(news.get("target_series_id", "")).upper()
        if not series_id or not series_id.replace("_", "").isalnum():
            raise ValueError("policy brief target_series_id must be a safe identifier")
        if series_id in seen:
            raise ValueError(f"duplicate policy brief target: {series_id}")
        seen.add(series_id)
        path = destination / f"{series_id}_policy_brief.md"
        path.write_text(render_multitarget_policy_brief(news, manifest))
        paths.append(path)
    return paths


def load_multitarget_artifacts(
    artifact_root: Path,
) -> tuple[dict[str, object], pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Load the exact completed multi-target reporting contract from disk."""

    manifest_path = artifact_root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict):
        raise ValueError("multi-target run_manifest.json must contain an object")
    if manifest.get("artifact_stage") != "multitarget_backtest_complete":
        raise ValueError("multi-target manifest is not marked backtest complete")
    return (
        manifest,
        pl.read_parquet(artifact_root / "metrics.parquet"),
        pl.read_parquet(artifact_root / "dm_comparisons.parquet"),
        pl.read_parquet(artifact_root / "target_revision_summary.parquet"),
    )


def write_multitarget_report(
    manifest: Mapping[str, object],
    metrics: pl.DataFrame,
    dm_comparisons: pl.DataFrame,
    revision_summary: pl.DataFrame,
    destination: Path,
    *,
    model_stability: pl.DataFrame | None = None,
    leakage_audit: pl.DataFrame | None = None,
) -> Path:
    """Write a rendered report to an explicit local destination."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        render_multitarget_report(
            manifest,
            metrics,
            dm_comparisons,
            revision_summary,
            model_stability=model_stability,
            leakage_audit=leakage_audit,
        )
    )
    return destination


__all__ = [
    "SYNTHETIC_NOTICE",
    "dm_diagnostic_summary",
    "load_multitarget_artifacts",
    "render_multitarget_policy_brief",
    "render_multitarget_report",
    "write_multitarget_policy_briefs",
    "write_multitarget_report",
]
