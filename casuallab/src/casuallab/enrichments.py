"""Optional weather, calendar, event, transit, and neighborhood panel adapters.

Adapters are intentionally file- and schema-driven. Missing optional inputs remain
missing and visible; they are never converted to "normal weather" or "no event".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class EnrichmentAdapter:
    """Declarative join contract for one optional external source."""

    name: str
    path: Path | None
    panel_keys: tuple[str, ...]
    source_keys: tuple[str, ...] | None = None
    value_columns: tuple[str, ...] = ()
    required: bool = False
    evidence_type: str = "observed_external_covariate"
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("enrichment name must not be empty")
        if not self.panel_keys:
            raise ValueError("panel_keys must not be empty")
        source_keys = self.source_keys or self.panel_keys
        if len(source_keys) != len(self.panel_keys):
            raise ValueError("panel_keys and source_keys must have the same length")


@dataclass(frozen=True)
class EnrichmentResult:
    panel: pd.DataFrame
    diagnostics: pd.DataFrame


def optional_adapter_registry() -> dict[str, dict[str, object]]:
    """Return documented feature contracts without requiring any external files."""

    return {
        "weather": {
            "typical_keys": ["time_bin"],
            "candidate_values": ["temperature", "precipitation", "snowfall", "wind_speed"],
            "caution": "Weather controls improve description/precision but do not instrument price.",
        },
        "holidays": {
            "typical_keys": ["service_date"],
            "candidate_values": ["holiday_name", "is_holiday"],
            "caution": "Unmatched dates are unknown until source coverage is verified.",
        },
        "events": {
            "typical_keys": ["zone_id", "time_bin"],
            "candidate_values": ["event_intensity", "venue_capacity", "event_category"],
            "caution": "Event occurrence may be endogenous to location and season.",
        },
        "transit_disruptions": {
            "typical_keys": ["zone_id", "time_bin"],
            "candidate_values": ["disruption_intensity", "affected_routes"],
            "caution": "Reported and unreported disruptions have different missingness mechanisms.",
        },
        "neighborhood": {
            "typical_keys": ["zone_id"],
            "candidate_values": ["income_index", "population", "vehicle_access", "demographics"],
            "caution": "Area characteristics are ecological and are not rider-level attributes.",
        },
    }


def _read_source(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"unsupported enrichment format for {path}; use CSV or Parquet")


def apply_optional_enrichments(
    panel: pd.DataFrame,
    adapters: list[EnrichmentAdapter] | tuple[EnrichmentAdapter, ...],
) -> EnrichmentResult:
    """Left-join available enrichments and return row-coverage diagnostics."""

    result = panel.copy()
    if result.empty:
        raise ValueError("panel must not be empty")
    diagnostics: list[dict[str, object]] = []
    for adapter in adapters:
        source_keys = adapter.source_keys or adapter.panel_keys
        missing_panel = set(adapter.panel_keys).difference(result.columns)
        if missing_panel:
            raise ValueError(
                f"panel missing keys for {adapter.name}: {sorted(missing_panel)}"
            )
        if adapter.path is None or not Path(adapter.path).exists():
            if adapter.required:
                raise FileNotFoundError(f"required {adapter.name} enrichment is unavailable")
            diagnostics.append(
                {
                    "name": adapter.name,
                    "status": "unavailable_optional",
                    "matched_rows": 0,
                    "total_rows": len(result),
                    "coverage_rate": None,
                    "evidence_type": adapter.evidence_type,
                }
            )
            continue

        source = _read_source(Path(adapter.path))
        missing_source = set(source_keys).difference(source.columns)
        if missing_source:
            raise ValueError(
                f"{adapter.name} source missing keys: {sorted(missing_source)}"
            )
        values = adapter.value_columns or tuple(
            column for column in source.columns if column not in source_keys
        )
        missing_values = set(values).difference(source.columns)
        if missing_values:
            raise ValueError(
                f"{adapter.name} source missing values: {sorted(missing_values)}"
            )
        selected = source[[*source_keys, *values]].copy()
        if selected.duplicated(list(source_keys)).any():
            raise ValueError(
                f"{adapter.name} source has duplicate join keys; aggregate explicitly first"
            )

        rename = dict(zip(source_keys, adapter.panel_keys, strict=True))
        value_rename = {column: f"{adapter.name}__{column}" for column in values}
        selected = selected.rename(columns={**rename, **value_rename})
        marker = f"_{adapter.name}_matched"
        selected[marker] = True
        result = result.merge(
            selected,
            on=list(adapter.panel_keys),
            how="left",
            validate="many_to_one",
        )
        matched = int(result[marker].fillna(False).sum())
        result = result.drop(columns=marker)
        diagnostics.append(
            {
                "name": adapter.name,
                "status": "joined",
                "matched_rows": matched,
                "total_rows": len(result),
                "coverage_rate": matched / len(result),
                "evidence_type": adapter.evidence_type,
                "source_metadata": adapter.source_metadata,
            }
        )
    return EnrichmentResult(result, pd.DataFrame(diagnostics))

