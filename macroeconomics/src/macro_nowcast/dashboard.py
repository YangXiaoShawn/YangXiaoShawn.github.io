"""Local Streamlit dashboard for generated, provenance-labeled artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import polars as pl
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "data" / "generated"
MULTITARGET_DIRNAME = "multitarget"
MULTITARGET_COMPLETE_STAGE = "multitarget_backtest_complete"
OFFICIAL_PILOT_DIRNAME = "official_pilot"
OFFICIAL_PILOT_COMPLETE_STAGE = "official_archive_empirical_pilot_complete"
TARGET_ORDER = ("PAYEMS", "CPILFESL", "GDPC1")

_TARGET_DEFAULTS: dict[str, dict[str, str]] = {
    "PAYEMS": {
        "target_name": "payems_change_mom_thousands",
        "target_frequency": "monthly",
        "target_units": "thousands_of_persons_change_mom",
        "target_formula": "current_level - prior_level",
    },
    "CPILFESL": {
        "target_name": "core_cpi_pct_change_mom",
        "target_frequency": "monthly",
        "target_units": "percent_change_mom_nonannualized",
        "target_formula": "100 * (current_level / prior_level - 1)",
    },
    "GDPC1": {
        "target_name": "real_gdp_pct_change_qoq_saar",
        "target_frequency": "quarterly",
        "target_units": "percent_change_qoq_saar",
        "target_formula": "100 * ((current_level / prior_level) ** 4 - 1)",
    },
}


@dataclass(frozen=True, slots=True)
class DashboardArtifactContext:
    """Resolved dashboard artifact root and completion-gated manifest."""

    root: Path
    manifest: dict[str, object]
    is_multitarget: bool
    is_official: bool = False
    evidence_tier: str = "synthetic_legacy"


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def multitarget_run_is_complete(root: Path) -> bool:
    """Return true only for the finalized multi-target artifact contract."""

    manifest = _read_json(root / "run_manifest.json")
    return bool(
        manifest.get("artifact_stage") == MULTITARGET_COMPLETE_STAGE
        and (root / "predictions.parquet").is_file()
        and (root / "metrics.parquet").is_file()
    )


def official_pilot_run_is_complete(root: Path) -> bool:
    """Return true only for the completed official-pilot contract."""

    manifest = _read_json(root / "run_manifest.json")
    return bool(
        manifest.get("artifact_stage") == OFFICIAL_PILOT_COMPLETE_STAGE
        and manifest.get("data_provenance") == "official_agency_archive"
        and (root / "predictions.parquet").is_file()
        and (root / "metrics.parquet").is_file()
        and (root / "metrics_by_regime_horizon.parquet").is_file()
        and (root / "final_evaluation_metrics.parquet").is_file()
        and (root / "hyperparameter_tuning.parquet").is_file()
        and (root / "feature_leakage_audit.parquet").is_file()
        and (root / "model_stability.parquet").is_file()
        and (root / "target_revision_summary.parquet").is_file()
        and (root / "news_updates.json").is_file()
    )


def available_dashboard_contexts(
    generated_root: Path = GENERATED,
) -> list[DashboardArtifactContext]:
    """Return every completed evidence tier without conflating their claims."""

    generated_root = generated_root.resolve()
    contexts: list[DashboardArtifactContext] = []
    official_root = generated_root / OFFICIAL_PILOT_DIRNAME
    if official_pilot_run_is_complete(official_root):
        contexts.append(
            DashboardArtifactContext(
                root=official_root,
                manifest=_read_json(official_root / "run_manifest.json"),
                is_multitarget=True,
                is_official=True,
                evidence_tier="official_archive_pilot",
            )
        )
    multitarget_root = generated_root / MULTITARGET_DIRNAME
    if multitarget_run_is_complete(multitarget_root):
        contexts.append(
            DashboardArtifactContext(
                root=multitarget_root,
                manifest=_read_json(multitarget_root / "run_manifest.json"),
                is_multitarget=True,
                evidence_tier="synthetic_multitarget",
            )
        )
    if not contexts:
        contexts.append(
            DashboardArtifactContext(
                root=generated_root,
                manifest=_read_json(generated_root / "run_manifest.json"),
                is_multitarget=False,
            )
        )
    return contexts


def detect_dashboard_artifacts(
    generated_root: Path = GENERATED,
) -> DashboardArtifactContext:
    """Prefer a completed multi-target run; otherwise return the legacy root."""

    generated_root = generated_root.resolve()
    multitarget_root = generated_root / MULTITARGET_DIRNAME
    if multitarget_run_is_complete(multitarget_root):
        return DashboardArtifactContext(
            root=multitarget_root,
            manifest=_read_json(multitarget_root / "run_manifest.json"),
            is_multitarget=True,
        )
    return DashboardArtifactContext(
        root=generated_root,
        manifest=_read_json(generated_root / "run_manifest.json"),
        is_multitarget=False,
    )


def filter_frame_for_target(
    frame: pl.DataFrame | None,
    target_series_id: str,
) -> pl.DataFrame | None:
    """Filter a combined artifact when it exposes an explicit target key."""

    if frame is None or "target_series_id" not in frame.columns:
        return frame
    return frame.filter(pl.col("target_series_id") == target_series_id)


def news_update_for_target(
    payload: Mapping[str, object],
    target_series_id: str,
) -> dict[str, object]:
    """Select one target update from the multi-target or legacy JSON contract."""

    target_series_id = target_series_id.upper()
    updates = payload.get("updates")
    if isinstance(updates, list):
        for update in updates:
            if (
                isinstance(update, Mapping)
                and str(update.get("target_series_id", "")).upper() == target_series_id
            ):
                return dict(update)
        return {}
    payload_target = payload.get("target_series_id")
    if payload_target is None or str(payload_target).upper() == target_series_id:
        return dict(payload)
    return {}


def _manifest_target_entries(manifest: Mapping[str, object]) -> list[Mapping[str, object]]:
    for key in ("target_definitions", "targets", "target_configs"):
        raw = manifest.get(key)
        if isinstance(raw, Mapping):
            entries = []
            for series_id, value in raw.items():
                if isinstance(value, Mapping):
                    entries.append({"target_series_id": str(series_id), **value})
            if entries:
                return entries
        if isinstance(raw, list):
            entries = [value for value in raw if isinstance(value, Mapping)]
            if entries:
                return entries
    return []


def available_target_ids(
    manifest: Mapping[str, object],
    frames: Iterable[pl.DataFrame | None] = (),
    *,
    include_multitarget_defaults: bool = False,
) -> list[str]:
    """Discover selectable target IDs from manifest and analytical artifacts."""

    discovered: set[str] = set(TARGET_ORDER if include_multitarget_defaults else ())
    for entry in _manifest_target_entries(manifest):
        value = entry.get("target_series_id", entry.get("series_id"))
        if isinstance(value, str) and value:
            discovered.add(value.upper())
    manifest_ids = manifest.get("target_series_ids")
    if isinstance(manifest_ids, list):
        discovered.update(str(value).upper() for value in manifest_ids)
    for frame in frames:
        if frame is not None and "target_series_id" in frame.columns:
            values = frame["target_series_id"].drop_nulls()
            discovered.update(str(value).upper() for value in values)
    legacy_target = manifest.get("target_series_id")
    if isinstance(legacy_target, str):
        discovered.add(legacy_target.upper())
    if not discovered and manifest:
        discovered.add("PAYEMS")
    ordered = [target for target in TARGET_ORDER if target in discovered]
    return ordered + sorted(discovered.difference(ordered))


def target_metadata(
    manifest: Mapping[str, object],
    target_series_id: str,
) -> dict[str, object]:
    """Resolve target metadata with explicit, formula-preserving fallbacks."""

    target_series_id = target_series_id.upper()
    metadata: dict[str, object] = {
        "target_series_id": target_series_id,
        **_TARGET_DEFAULTS.get(target_series_id, {}),
    }
    for entry in _manifest_target_entries(manifest):
        series_id = entry.get("target_series_id", entry.get("series_id"))
        if str(series_id).upper() == target_series_id:
            metadata.update(entry)
            break
    aliases = {
        "name": "target_name",
        "frequency": "target_frequency",
        "units": "target_units",
        "formula": "target_formula",
        "evaluation_start": "sample_start",
        "evaluation_end": "sample_end",
    }
    for source, destination in aliases.items():
        if source in metadata and destination not in metadata:
            metadata[destination] = metadata[source]
    windows = manifest.get("evaluation_windows")
    if isinstance(windows, Mapping):
        window = windows.get(target_series_id)
        if isinstance(window, Mapping):
            metadata.setdefault("sample_start", window.get("start"))
            metadata.setdefault("sample_end", window.get("end"))
    return metadata


def target_caption(
    manifest: Mapping[str, object],
    target_series_id: str,
    frame: pl.DataFrame | None = None,
) -> str:
    """Build the mandatory target/formula/frequency/units/sample caption."""

    metadata = target_metadata(manifest, target_series_id)
    sample_start = metadata.get("sample_start", manifest.get("evaluation_start", "unknown"))
    sample_end = metadata.get("sample_end", manifest.get("evaluation_end", "unknown"))
    if frame is not None and not frame.is_empty() and "target_period" in frame.columns:
        sample_start = frame["target_period"].min()
        sample_end = frame["target_period"].max()
    return (
        f"Target {target_series_id} ({metadata.get('target_name', 'unknown')}) | "
        f"formula: {metadata.get('target_formula', 'not recorded')} | "
        f"frequency: {metadata.get('target_frequency', 'unknown')} | "
        f"units: {metadata.get('target_units', 'unknown')} | "
        f"sample: {sample_start} to {sample_end}"
    )


def dm_status_message(dm: pl.DataFrame | None, target_series_id: str) -> str:
    """Return an honest interpretation of target-specific DM diagnostics."""

    selected = filter_frame_for_target(dm, target_series_id)
    if selected is None or selected.is_empty():
        return "No Diebold-Mariano comparison is available for this target."
    if "valid" not in selected.columns:
        return (
            "DM rows lack an explicit validity flag; no model-superiority inference is made."
        )
    valid_count = selected.filter(pl.col("valid") == True).height  # noqa: E712
    invalid = selected.filter(pl.col("valid") != True)  # noqa: E712
    details: list[str] = []
    if not invalid.is_empty():
        for row in invalid.select(
            [column for column in ("status", "reason") if column in invalid.columns]
        ).unique().to_dicts():
            detail = ": ".join(str(value) for value in row.values() if value)
            if detail:
                details.append(detail)
    if valid_count == 0:
        suffix = f" ({'; '.join(details)})" if details else ""
        return (
            "No valid DM inference is available; the comparison is descriptive only"
            f"{suffix}. Small samples, especially quarterly GDP, are reported as insufficient."
        )
    suffix = f" Invalid rows: {'; '.join(details)}." if details else ""
    is_official = (
        "data_provenance" in selected.columns
        and selected["data_provenance"].drop_nulls().unique().to_list()
        == ["official_agency_archive"]
    )
    if is_official:
        return (
            "Valid DM statistics are scoped official-pilot diagnostics and do not establish "
            f"broad model superiority.{suffix}"
        )
    return (
        "Valid DM statistics are synthetic diagnostics only and do not establish model "
        f"superiority.{suffix}"
    )


def _load_parquet(name: str, root: Path = GENERATED) -> pl.DataFrame | None:
    path = root / name
    return pl.read_parquet(path) if path.exists() else None


def _load_manifest(root: Path = GENERATED) -> dict[str, object]:
    return _read_json(root / "run_manifest.json")


def _load_json(name: str, root: Path = GENERATED) -> dict[str, object]:
    return _read_json(root / name)


def _empty_message() -> None:
    st.info("No generated artifacts found. Run `make reproduce-sample` first.")


def main() -> None:
    st.set_page_config(page_title="Real-Time Macro Nowcast", layout="wide")
    contexts = available_dashboard_contexts()
    if len(contexts) > 1:
        selected_tier = st.selectbox(
            "Evidence tier",
            [context.evidence_tier for context in contexts],
            format_func=lambda value: {
                "official_archive_pilot": "Official BLS/BEA/DOL/Fed archive pilot",
                "synthetic_multitarget": "Synthetic multi-target acceptance",
            }.get(value, value),
        )
        context = next(
            context for context in contexts if context.evidence_tier == selected_tier
        )
    else:
        context = contexts[0]
    artifact_root = context.root
    manifest = context.manifest
    fixture_label = str(
        manifest.get("data_provenance", manifest.get("fixture_label", "unknown_data_mode"))
    )

    st.title("Real-Time Macro Nowcasting and Policy Shock Engine")
    if fixture_label == "synthetic_fixture":
        st.warning(
            "SYNTHETIC FIXTURE DEMONSTRATION — charts and metrics validate the pipeline; "
            "they are not empirical findings about the economy."
        )
    elif context.is_official:
        st.warning(
            "SCOPED EMPIRICAL PILOT — official CES/core-CPI/GDP target archives with "
            "own/cross-target lags, eight BLS CES sector series, BLS CPS unemployment, "
            "DOL weekly claims, Fed G.17 industrial production, Census MARTS retail-sales, "
            "and Census NRC housing-start vintages. Verified PAYEMS, CPI, and GDP target "
            "events use exact agency-header clocks; unsupported PAYEMS events use prior-"
            "New-York-day EOD origins. DOL, G.17, MARTS, and NRC retain their source clocks. "
            "The full cross-agency "
            "predictor set and broad model or policy claims remain unsupported."
        )
    else:
        st.caption(f"Data mode: {fixture_label}")

    if context.is_official:
        observations = _load_parquet(
            "official_vintage_observations.parquet",
            GENERATED / "official_vintages",
        )
    else:
        observation_name = (
            "observations.parquet"
            if context.is_multitarget
            else "observation_vintages.parquet"
        )
        observations = _load_parquet(observation_name, artifact_root)
    predictions = _load_parquet("predictions.parquet", artifact_root)
    metrics = _load_parquet("metrics.parquet", artifact_root)
    final_evaluation_metrics = _load_parquet(
        "final_evaluation_metrics.parquet", artifact_root
    )
    hyperparameter_tuning = _load_parquet("hyperparameter_tuning.parquet", artifact_root)
    grouped_metrics = _load_parquet("metrics_by_regime_horizon.parquet", artifact_root)
    model_stability = _load_parquet("model_stability.parquet", artifact_root)
    revisions = _load_parquet(
        "target_revision_summary.parquet" if context.is_multitarget else "revisions.parquet",
        artifact_root,
    )
    target_revision_summary = _load_parquet("target_revision_summary.parquet", artifact_root)
    dm_comparisons = _load_parquet("dm_comparisons.parquet", artifact_root)
    releases = _load_parquet(
        "forecast_origins.parquet" if context.is_official else "release_calendar.parquet",
        artifact_root,
    )
    features = _load_parquet("features_long.parquet", artifact_root)
    news_payload = _load_json(
        "news_updates.json" if context.is_multitarget else "news_update.json",
        artifact_root,
    )
    observation_availability_column = "availability_timestamp"
    if observations is not None and (
        observation_availability_column not in observations.columns
        or observations[observation_availability_column].drop_nulls().is_empty()
    ):
        observation_availability_column = "availability_date"

    if all(frame is None for frame in (observations, predictions, metrics, revisions, releases)):
        _empty_message()
        return

    target_options = available_target_ids(
        manifest,
        (predictions, metrics, revisions, features, dm_comparisons),
        include_multitarget_defaults=context.is_multitarget,
    ) or ["PAYEMS"]
    selected_target = st.selectbox(
        "Target",
        target_options,
        format_func=lambda value: (
            f"{value} — {target_metadata(manifest, value).get('target_name', 'configured')}"
        ),
        key="dashboard_target",
    )
    predictions = filter_frame_for_target(predictions, selected_target)
    metrics = filter_frame_for_target(metrics, selected_target)
    final_evaluation_metrics = filter_frame_for_target(
        final_evaluation_metrics, selected_target
    )
    hyperparameter_tuning = filter_frame_for_target(
        hyperparameter_tuning, selected_target
    )
    grouped_metrics = filter_frame_for_target(grouped_metrics, selected_target)
    model_stability = filter_frame_for_target(model_stability, selected_target)
    revisions = filter_frame_for_target(revisions, selected_target)
    target_revision_summary = filter_frame_for_target(
        target_revision_summary, selected_target
    )
    dm_comparisons = filter_frame_for_target(dm_comparisons, selected_target)
    releases = filter_frame_for_target(releases, selected_target)
    features = filter_frame_for_target(features, selected_target)
    horizon_options = (
        sorted(predictions["horizon"].drop_nulls().unique().to_list())
        if predictions is not None
        and not predictions.is_empty()
        and "horizon" in predictions.columns
        else [manifest.get("horizon", 0)]
    )
    horizon_label = st.selectbox(
        "Forecast horizon",
        horizon_options,
        format_func=lambda value: (
            "0 — target-release nowcast"
            if value == 0
            else "1 — one native target period ahead"
            if value == 1
            else str(value)
        ),
        key="dashboard_horizon",
    )
    horizon_frames = [
        predictions,
        metrics,
        final_evaluation_metrics,
        hyperparameter_tuning,
        grouped_metrics,
        model_stability,
        target_revision_summary,
        dm_comparisons,
    ]
    filtered_horizon_frames = [
        frame.filter(pl.col("horizon") == horizon_label)
        if frame is not None and "horizon" in frame.columns
        else frame
        for frame in horizon_frames
    ]
    (
        predictions,
        metrics,
        final_evaluation_metrics,
        hyperparameter_tuning,
        grouped_metrics,
        model_stability,
        target_revision_summary,
        dm_comparisons,
    ) = filtered_horizon_frames
    selected_metadata = target_metadata(manifest, selected_target)
    news = news_update_for_target(news_payload, selected_target)
    target_label = str(selected_metadata.get("target_name", selected_target))
    caption = target_caption(manifest, selected_target, predictions)
    st.caption(caption)
    evaluation_sample = caption.rsplit("sample: ", maxsplit=1)[-1]

    overview, vintage_tab, forecast_tab, model_tab, contribution_tab, release_tab, health_tab = (
        st.tabs(
            [
                "Overview",
                "Vintages",
                "Nowcasts",
                "Models",
                "Contributions",
                "Calendar",
                "Pipeline health",
            ]
        )
    )

    with overview:
        st.subheader("Run contract")
        st.caption(
            "Completed official target-archive pilot artifacts"
            if context.is_official
            else "Completed multi-target artifacts"
            if context.is_multitarget
            else "Legacy payroll artifacts (multi-target run absent or incomplete)"
        )
        st.json(manifest)
        if observations is not None:
            cols = st.columns(3)
            cols[0].metric("Series", observations["series_id"].n_unique())
            cols[1].metric("Vintage rows", observations.height)
            cols[2].metric(
                "Latest availability",
                str(observations[observation_availability_column].max()),
            )
            st.subheader("Latest generated observations")
            latest_rows = (
                observations.sort(
                    ["series_id", "observation_date", observation_availability_column]
                )
                .group_by("series_id", maintain_order=True)
                .tail(1)
                .select(
                    "series_id",
                    "observation_date",
                    "value",
                    "units",
                    observation_availability_column,
                    "provenance_label",
                )
                .sort("series_id")
            )
            st.dataframe(latest_rows.to_pandas(), width="stretch")

    with vintage_tab:
        if observations is None:
            _empty_message()
        else:
            options = observations["series_id"].unique().sort().to_list()
            chosen = st.selectbox("Series", options)
            series = observations.filter(pl.col("series_id") == chosen).sort(
                ["observation_date", observation_availability_column]
            )
            fig = px.line(
                series.to_pandas(),
                x="observation_date",
                y="value",
                color=observation_availability_column,
                markers=True,
                title=(
                    f"{chosen} vintage histories | {fixture_label} | target {target_label} | "
                    f"horizon {horizon_label} | "
                    f"sample {series['observation_date'].min()} to "
                    f"{series['observation_date'].max()}"
                ),
            )
            st.plotly_chart(fig, width="stretch")
            if revisions is not None and not revisions.is_empty():
                shown_revisions = (
                    revisions.filter(pl.col("series_id") == chosen)
                    if "series_id" in revisions.columns
                    else revisions
                )
                st.dataframe(shown_revisions.to_pandas(), width="stretch")
                revision_value = next(
                    (
                        column
                        for column in ("mean_abs_target_revision", "mean_abs_revision")
                        if column in revisions.columns
                    ),
                    None,
                )
                revision_axis = next(
                    (
                        column
                        for column in ("series_id", "model_id", "target_name")
                        if column in revisions.columns
                    ),
                    None,
                )
                if revision_value and revision_axis:
                    revision_fig = px.bar(
                        revisions.sort(revision_value, descending=True).to_pandas(),
                        x=revision_axis,
                        y=revision_value,
                        title=f"Revision summary | {caption} | {fixture_label}",
                    )
                    st.plotly_chart(revision_fig, width="stretch")
            if target_revision_summary is not None and not target_revision_summary.is_empty():
                st.subheader("Target revision effect on forecast error")
                st.dataframe(target_revision_summary.to_pandas(), width="stretch")

    with forecast_tab:
        if predictions is None or predictions.is_empty():
            _empty_message()
        else:
            pdf = predictions.sort("target_period").to_pandas()
            target = target_label
            horizon = horizon_label
            sample = f"{pdf['target_period'].min()} to {pdf['target_period'].max()}"
            fig = px.line(
                pdf,
                x="target_period",
                y="prediction",
                color="model_id",
                line_dash="data_mode",
                title=(
                    f"Expanding-window nowcasts | target {target} | horizon {horizon} | "
                    f"{fixture_label} | sample {sample}"
                ),
            )
            st.plotly_chart(fig, width="stretch")
            latest_period = pdf["target_period"].max()
            st.dataframe(
                pdf.loc[pdf["target_period"] == latest_period],
                width="stretch",
            )
            model_choice = st.selectbox(
                "Interval model",
                sorted(pdf["model_id"].unique()),
            )
            mode_choice = st.selectbox(
                "Interval data mode",
                sorted(pdf["data_mode"].unique()),
            )
            distribution = pdf.loc[
                (pdf["model_id"] == model_choice) & (pdf["data_mode"] == mode_choice)
            ].sort_values("target_period")
            interval_fig = go.Figure()
            interval_fig.add_trace(
                go.Scatter(
                    x=distribution["target_period"],
                    y=distribution["lower"],
                    mode="lines",
                    line={"width": 0},
                    name="lower",
                )
            )
            interval_fig.add_trace(
                go.Scatter(
                    x=distribution["target_period"],
                    y=distribution["upper"],
                    mode="lines",
                    fill="tonexty",
                    name="80% prior-residual interval",
                )
            )
            interval_fig.add_trace(
                go.Scatter(
                    x=distribution["target_period"],
                    y=distribution["prediction"],
                    mode="lines+markers",
                    name="forecast",
                )
            )
            interval_fig.add_trace(
                go.Scatter(
                    x=distribution["target_period"],
                    y=distribution["actual"],
                    mode="lines",
                    name="realization",
                )
            )
            interval_fig.update_layout(
                title=(
                    f"Forecast distribution | {model_choice} | {mode_choice} | "
                    f"{fixture_label} | target {target} | horizon {horizon} | sample {sample}"
                )
            )
            st.plotly_chart(interval_fig, width="stretch")

    with model_tab:
        if metrics is None or metrics.is_empty():
            _empty_message()
        else:
            displayed_metrics = (
                final_evaluation_metrics
                if context.is_official
                and final_evaluation_metrics is not None
                and not final_evaluation_metrics.is_empty()
                else metrics
            )
            metric_options = [
                name
                for name in ["rmse", "mae", "bias", "interval_coverage"]
                if name in displayed_metrics.columns
            ]
            metric_name = st.selectbox("Metric", metric_options) if metric_options else None
            mdf = displayed_metrics.to_pandas()
            if metric_name is not None:
                fig = px.bar(
                    mdf,
                    x="model_id",
                    y=metric_name,
                    color="data_mode",
                    barmode="group",
                    title=f"Model diagnostics: {metric_name} | {caption} | {fixture_label}",
                )
                st.plotly_chart(fig, width="stretch")
            st.dataframe(mdf, width="stretch")
            if context.is_official and displayed_metrics is final_evaluation_metrics:
                st.caption(
                    "Primary ranking table: untouched final-evaluation block. "
                    "Hyperparameters were selected without these rows."
                )
                st.subheader("All-OOS descriptive metrics")
                st.dataframe(metrics.to_pandas(), width="stretch")
                if hyperparameter_tuning is not None:
                    st.subheader("Selected advanced-model hyperparameters")
                    st.dataframe(
                        hyperparameter_tuning.filter(pl.col("selected")).to_pandas(),
                        width="stretch",
                    )
            st.caption(
                "Official-pilot metrics are scoped empirical diagnostics and do not "
                "establish broad model superiority."
                if context.is_official
                else "Synthetic metrics are engineering diagnostics and do not establish "
                "model superiority."
            )
            if dm_comparisons is not None:
                st.subheader("Diebold-Mariano diagnostics")
                st.info(dm_status_message(dm_comparisons, selected_target))
                if not dm_comparisons.is_empty():
                    st.dataframe(dm_comparisons.to_pandas(), width="stretch")
            if grouped_metrics is not None:
                st.subheader("Configured regime and horizon breakdown")
                st.caption(
                    "NBER peak/trough labels are ex-post evaluation groups, never model "
                    "inputs; small official-pilot recession samples are descriptive."
                    if context.is_official
                    else "Fixture regimes are deterministic calendar partitions, not "
                    "identified economic regimes."
                )
                st.dataframe(grouped_metrics.to_pandas(), width="stretch")
            if model_stability is not None:
                st.subheader("Stability across vintage modes")
                st.dataframe(model_stability.to_pandas(), width="stretch")

    with contribution_tab:
        if not news:
            _empty_message()
        else:
            st.subheader(
                "Fixed-model official archive release update"
                if context.is_official
                else "Fixed-model simulated release update"
            )
            cols = st.columns(3)
            cols[0].metric("Previous nowcast", f"{news['previous_nowcast']:.3f}")
            cols[1].metric("Updated nowcast", f"{news['updated_nowcast']:.3f}")
            cols[2].metric("Revision", f"{news['forecast_revision']:.3f}")
            contributions = pl.DataFrame(news.get("contributions", []))
            if not contributions.is_empty():
                contribution_fig = px.bar(
                    contributions.sort("contribution").to_pandas(),
                    x="contribution",
                    y="feature",
                    orientation="h",
                    title=(
                        f"Forecast contributions | {news.get('attribution_label')} attribution | "
                        f"series {news.get('release_series_id')} | vintage "
                        f"{news.get('data_mode')} | target {target_label} | horizon "
                        f"{news.get('horizon', horizon_label)} | sample {evaluation_sample}"
                    ),
                )
                st.plotly_chart(contribution_fig, width="stretch")
            st.caption(
                "Contribution is mechanical fixed-model accounting, not causal attribution."
            )

    with release_tab:
        if releases is None or releases.is_empty():
            _empty_message()
        else:
            release_time_column = next(
                (
                    column
                    for column in (
                        "release_timestamp",
                        "release_ts",
                        "target_release_timestamp",
                    )
                    if column in releases.columns
                ),
                None,
            )
            displayed_releases = (
                releases.sort(release_time_column, descending=True)
                if release_time_column
                else releases
            )
            st.dataframe(
                displayed_releases.head(100).to_pandas(),
                width="stretch",
            )

    with health_tab:
        checks: list[dict[str, object]] = []
        artifact_names = (
            [
                "forecast_origins.parquet",
                "features_long.parquet",
                "targets.parquet",
                "research_datasets.parquet",
                "predictions.parquet",
                "metrics.parquet",
                "final_evaluation_metrics.parquet",
                "hyperparameter_tuning.parquet",
                "metrics_by_regime_horizon.parquet",
                "feature_leakage_audit.parquet",
                "dm_comparisons.parquet",
                "revision_details.parquet",
                "revisions.parquet",
                "model_stability.parquet",
                "target_revision_effects.parquet",
                "target_revision_summary.parquet",
                "news_updates.json",
                "policy_briefs/PAYEMS_official_policy_brief.md",
                "policy_briefs/CPILFESL_official_policy_brief.md",
                "policy_briefs/GDPC1_official_policy_brief.md",
                "official_pilot_report.md",
                "official_pilot.duckdb",
                "run_manifest.json",
            ]
            if context.is_official
            else
            [
                "observations.parquet",
                "release_calendar.parquet",
                "forecast_origins.parquet",
                "features_long.parquet",
                "targets.parquet",
                "research_datasets.parquet",
                "predictions.parquet",
                "metrics.parquet",
                "metrics_by_regime_horizon.parquet",
                "model_stability.parquet",
                "feature_leakage_audit.parquet",
                "dm_comparisons.parquet",
                "target_revision_summary.parquet",
                "news_updates.json",
                "run_manifest.json",
            ]
            if context.is_multitarget
            else [
                "observation_vintages.parquet",
                "release_calendar.parquet",
                "features_long.parquet",
                "predictions.parquet",
                "metrics.parquet",
                "revisions.parquet",
                "macro_nowcast.duckdb",
                "run_manifest.json",
            ]
        )
        for name in artifact_names:
            path = artifact_root / name
            checks.append(
                {
                    "artifact": name,
                    "present": path.exists(),
                    "bytes": path.stat().st_size if path.exists() else None,
                }
            )
        st.dataframe(checks, width="stretch")
        if observations is not None:
            latest_availability = observations[observation_availability_column].max()
            freshness = (
                observations.sort(
                    ["series_id", "observation_date", observation_availability_column]
                )
                .group_by("series_id", maintain_order=True)
                .tail(1)
                .select(
                    "series_id",
                    "observation_date",
                    observation_availability_column,
                    (
                        pl.lit(latest_availability)
                        - pl.col(observation_availability_column)
                    )
                    .dt.total_days()
                    .alias("days_behind_fixture_latest"),
                )
                .sort("series_id")
            )
            st.subheader("Data freshness")
            st.dataframe(freshness.to_pandas(), width="stretch")
        if features is not None and "max_source_availability" in features.columns:
            violations = features.filter(
                (pl.col("information_set_mode") == "as_of")
                & (pl.col("max_source_availability") > pl.col("as_of_timestamp"))
            ).height
            st.metric("As-of availability violations", violations)


if __name__ == "__main__":
    main()
