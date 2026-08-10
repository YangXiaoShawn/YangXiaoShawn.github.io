import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from casuallab.data import sha256_file
from casuallab.nyc_events import (
    EVENT_EVIDENCE_LABEL,
    EVENT_SNAPSHOT_SHA256,
    HOLIDAY_SNAPSHOT_SHA256,
    NYCEventsConfig,
    build_nyc_event_calendar,
    event_demand_associations,
    normalize_nyc_holiday_calendar,
    normalize_nyc_permitted_events,
    write_nyc_events_bundle,
)


def test_committed_january_snapshots_match_pinned_official_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    holiday_path = root / "data/nyc_events/raw/official_holidays_2024-01.csv"
    event_path = root / "data/nyc_events/raw/nyc_permitted_events_overlap_2024-01.csv"

    assert holiday_path.stat().st_size == 185
    assert event_path.stat().st_size == 1_307_528
    assert sha256_file(holiday_path) == HOLIDAY_SNAPSHOT_SHA256
    assert sha256_file(event_path) == EVENT_SNAPSHOT_SHA256
    holidays = normalize_nyc_holiday_calendar(holiday_path)
    events = normalize_nyc_permitted_events(event_path)
    assert len(holidays) == 31
    assert holidays.columns[:3].tolist() == [
        "service_date",
        "federal_holiday_name",
        "nyc_city_employee_holiday_name",
    ]
    assert int(holidays["is_any_official_holiday"].sum()) == 2
    assert len(events) == 6007
    assert events["event_id"].nunique() == 951
    assert int(events["invalid_permit_interval"].sum()) == 1
    assert int(events["zero_duration_permit_interval"].sum()) == 8
    assert int((~events["usable_for_daily_expansion"]).sum()) == 9


def _snapshots(root: Path) -> tuple[Path, Path, NYCEventsConfig]:
    raw = root / "data/nyc_events/raw"
    raw.mkdir(parents=True, exist_ok=True)
    holidays = raw / "holidays.csv"
    pd.DataFrame(
        {
            "service_date": ["2024-01-01"],
            "federal_holiday_name": ["New Year's Day"],
            "nyc_city_employee_holiday_name": ["New Year's Day"],
        }
    ).to_csv(holidays, index=False)
    events = raw / "events.csv"
    pd.DataFrame(
        {
            "event_id": ["100", "101", "101", "102"],
            "event_name": ["Major Night", "Public Walk", "Public Walk", "Bad Clock"],
            "start_date_time": [
                "2023-12-31T20:00:00.000",
                "2024-01-01T10:00:00.000",
                "2024-01-01T10:00:00.000",
                "2024-01-03T23:00:00.000",
            ],
            "end_date_time": [
                "2024-01-01T02:00:00.000",
                "2024-01-02T11:00:00.000",
                "2024-01-02T11:00:00.000",
                "2024-01-03T01:00:00.000",
            ],
            "event_agency": ["Agency A", "Agency B", "Agency B", "Agency C"],
            "event_type": ["Special Event", "Parade", "Parade", "Special Event"],
            "event_borough": ["Manhattan", "Brooklyn", "Brooklyn", "Queens"],
            "event_location": ["A", "B", "C", "D"],
            "community_board": ["1,", "2,", "2,", "3,"],
            "police_precinct": ["1,", "2,", "2,", "3,"],
        }
    ).to_csv(events, index=False)
    config = NYCEventsConfig(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 3),
        expected_holiday_rows=1,
        expected_event_rows=4,
        expected_unique_event_ids=3,
        holiday_snapshot_sha256=hashlib.sha256(holidays.read_bytes()).hexdigest(),
        event_snapshot_sha256=hashlib.sha256(events.read_bytes()).hexdigest(),
        major_event_ids=("100",),
        public_gathering_event_types=("Parade",),
    )
    return holidays, events, config


def _panel(path: Path) -> pd.DataFrame:
    rows = []
    for day_index, day in enumerate(
        (date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)), start=1
    ):
        for hour in range(24):
            for zone in ("1", "2"):
                rows.append(
                    {
                        "service_date": day,
                        "hour": hour,
                        "zone_id": zone,
                        "trip_count": 10 * day_index + hour + int(zone),
                    }
                )
    frame = pd.DataFrame(rows)
    frame.to_parquet(path, index=False)
    return frame


def _data_manifest(root: Path, panel_path: Path, trip_sum: int) -> Path:
    manifest = root / "data/nyc_full/manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "config": {"source": "nyc_hvfhv", "mode": "full"},
                "metadata": {
                    "evidence_label": "descriptive_real_data",
                    "causal_claim": False,
                    "full_month_processing": {
                        "row_conservation": {"zone_time_trip_sum": trip_sum}
                    },
                },
                "files": [
                    {
                        "path": str(panel_path.relative_to(root)),
                        "bytes": panel_path.stat().st_size,
                        "sha256": sha256_file(panel_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_calendar_and_events_normalize_without_inventing_precision(tmp_path: Path) -> None:
    holiday_path, event_path, config = _snapshots(tmp_path)

    holidays = normalize_nyc_holiday_calendar(holiday_path, config)
    events = normalize_nyc_permitted_events(event_path, config)

    assert len(holidays) == 3
    assert holidays["is_any_official_holiday"].tolist() == [True, False, False]
    assert not holidays["causal_claim"].any()
    assert len(events) == 4
    assert events["event_id"].nunique() == 3
    assert events["invalid_permit_interval"].tolist() == [False, False, False, True]
    assert not events["zero_duration_permit_interval"].any()
    assert events["researcher_defined_major_event"].sum() == 1
    assert set(events["evidence_label"]) == {EVENT_EVIDENCE_LABEL}


def test_event_calendar_deduplicates_event_ids_and_excludes_bad_interval(
    tmp_path: Path,
) -> None:
    holiday_path, event_path, config = _snapshots(tmp_path)
    holidays = normalize_nyc_holiday_calendar(holiday_path, config)
    events = normalize_nyc_permitted_events(event_path, config)

    calendar, type_daily = build_nyc_event_calendar(holidays, events, config)

    assert calendar["active_permitted_event_count"].tolist() == [2, 1, 0]
    assert calendar["active_public_gathering_permitted_event_count"].tolist() == [1, 1, 0]
    assert calendar["active_major_permitted_event_count"].tolist() == [1, 0, 0]
    assert calendar["is_above_monthly_median_permit_intensity_day"].tolist() == [
        True,
        False,
        False,
    ]
    assert int(type_daily["active_unique_permitted_events"].sum()) == 3
    assert not type_daily["causal_claim"].any()


def test_event_calendar_uses_positive_duration_half_open_intervals(
    tmp_path: Path,
) -> None:
    holiday_path, _, config = _snapshots(tmp_path)
    holidays = normalize_nyc_holiday_calendar(holiday_path, config)
    events = pd.DataFrame(
        {
            "event_id": ["valid", "zero"],
            "event_name": ["Ends at midnight", "No duration"],
            "event_type": ["Parade", "Parade"],
            "permit_start_local": pd.to_datetime(
                ["2024-01-01 20:00:00", "2024-01-02 12:00:00"]
            ),
            "permit_end_local": pd.to_datetime(
                ["2024-01-02 00:00:00", "2024-01-02 12:00:00"]
            ),
            "usable_for_daily_expansion": [True, False],
            "researcher_defined_major_event": [False, False],
            "public_gathering_permit_subset": [True, True],
        }
    )

    calendar, type_daily = build_nyc_event_calendar(holidays, events, config)

    assert calendar["active_permitted_event_count"].tolist() == [1, 0, 0]
    assert int(type_daily["active_unique_permitted_events"].sum()) == 1


def test_event_associations_are_descriptive_complete_and_trip_conserving(
    tmp_path: Path,
) -> None:
    holiday_path, event_path, config = _snapshots(tmp_path)
    holidays = normalize_nyc_holiday_calendar(holiday_path, config)
    events = normalize_nyc_permitted_events(event_path, config)
    calendar, type_daily = build_nyc_event_calendar(holidays, events, config)
    panel_path = tmp_path / "panel.parquet"
    panel = _panel(panel_path)

    daily, hourly, summary = event_demand_associations(
        [panel_path], calendar, events, type_daily, config
    )

    assert len(daily) == 3
    assert len(hourly) == 24
    assert summary["causal_claim"] is False
    assert summary["coverage"]["joined_date_hours"] == 72
    assert summary["coverage"]["source_permit_rows"] == 4
    assert summary["coverage"]["source_unique_event_ids"] == 3
    assert summary["coverage"]["invalid_interval_rows_retained_but_not_expanded"] == 1
    assert summary["coverage"]["weekend_days"] == 0
    assert summary["conservation"]["daily_trip_sum"] == int(panel["trip_count"].sum())
    assert summary["identification_checks"]["causal_effect_identified"] is False
    assert summary["identification_checks"][
        "major_event_contrast_separately_identifies_event_effect"
    ] is False
    assert (
        summary["associations"][
            "above_vs_at_or_below_median_permit_intensity_weekdays_only"
        ]["exposed_days"]
        == 1
    )
    assert "confound" in " ".join(summary["limitations"])


def test_event_snapshot_hash_and_query_order_fail_closed(tmp_path: Path) -> None:
    _, event_path, config = _snapshots(tmp_path)
    event_path.write_text(event_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        normalize_nyc_permitted_events(event_path, config)

    _, ordered_path, _ = _snapshots(tmp_path / "ordered")
    shuffled = pd.read_csv(ordered_path, dtype=str, keep_default_na=False).iloc[::-1]
    shuffled.to_csv(ordered_path, index=False)
    shuffled_config = NYCEventsConfig(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 3),
        expected_holiday_rows=1,
        expected_event_rows=4,
        expected_unique_event_ids=3,
        holiday_snapshot_sha256="0" * 64,
        event_snapshot_sha256=hashlib.sha256(ordered_path.read_bytes()).hexdigest(),
        major_event_ids=("100",),
        public_gathering_event_types=("Parade",),
    )
    with pytest.raises(ValueError, match="query order"):
        normalize_nyc_permitted_events(ordered_path, shuffled_config)


def test_event_bundle_verifies_lineage_and_publishes_manifest_last(tmp_path: Path) -> None:
    holiday_path, event_path, config = _snapshots(tmp_path)
    panel_dir = tmp_path / "data/nyc_full/panel/zone_time"
    panel_dir.mkdir(parents=True)
    panel_path = panel_dir / "part.parquet"
    panel = _panel(panel_path)
    data_manifest = _data_manifest(tmp_path, panel_path, int(panel["trip_count"].sum()))
    output = tmp_path / "artifacts/nyc_full/events"

    artifacts = write_nyc_events_bundle(
        holiday_path,
        event_path,
        panel_dir,
        data_manifest,
        output,
        project_root=tmp_path,
        config=config,
    )

    assert all(path.is_file() for path in artifacts.paths())
    assert not (output / "NYC_EVENTS_INCOMPLETE.json").exists()
    payload = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    assert payload["evidence_label"] == EVENT_EVIDENCE_LABEL
    assert payload["causal_claim"] is False
    assert payload["checks"]["trip_conservation"] is True
    assert payload["checks"]["joined_days"] == 3
    assert {entry["role"] for entry in payload["files"]} == {
        "normalized_daily_calendar",
        "normalized_permit_records",
        "daily_permit_type_counts",
        "joined_daily_trip_panel",
        "descriptive_hourly_profiles",
        "descriptive_summary",
    }
    assert {entry["role"] for entry in payload["inputs"]} == {
        "official_holiday_snapshot",
        "official_nyc_permitted_events_snapshot",
        "nyc_full_data_manifest",
        "nyc_full_zone_time_panel",
    }
    assert all(
        not Path(entry["path"]).is_absolute()
        for collection in (payload["files"], payload["inputs"])
        for entry in collection
    )


def test_event_bundle_leaves_marker_and_no_manifest_on_stale_panel(tmp_path: Path) -> None:
    holiday_path, event_path, config = _snapshots(tmp_path)
    panel_dir = tmp_path / "data/nyc_full/panel/zone_time"
    panel_dir.mkdir(parents=True)
    panel_path = panel_dir / "part.parquet"
    panel = _panel(panel_path)
    data_manifest = _data_manifest(tmp_path, panel_path, int(panel["trip_count"].sum()))
    output = tmp_path / "artifacts/nyc_full/events"

    write_nyc_events_bundle(
        holiday_path,
        event_path,
        panel_dir,
        data_manifest,
        output,
        project_root=tmp_path,
        config=config,
    )
    assert (output / "manifest.json").is_file()
    panel_path.write_bytes(panel_path.read_bytes() + b"tamper")

    with pytest.raises(ValueError, match="lineage mismatch"):
        write_nyc_events_bundle(
            holiday_path,
            event_path,
            panel_dir,
            data_manifest,
            output,
            project_root=tmp_path,
            config=config,
        )
    assert (output / "NYC_EVENTS_INCOMPLETE.json").is_file()
    assert not (output / "manifest.json").exists()


def test_event_bundle_rejects_stale_declared_panel_partition(tmp_path: Path) -> None:
    holiday_path, event_path, config = _snapshots(tmp_path)
    panel_dir = tmp_path / "data/nyc_full/panel/zone_time"
    panel_dir.mkdir(parents=True)
    panel_path = panel_dir / "part.parquet"
    panel = _panel(panel_path)
    data_manifest = _data_manifest(tmp_path, panel_path, int(panel["trip_count"].sum()))
    payload = json.loads(data_manifest.read_text(encoding="utf-8"))
    payload["files"].append(
        {
            "path": str((panel_dir / "stale.parquet").relative_to(tmp_path)),
            "bytes": 1,
            "sha256": "0" * 64,
        }
    )
    data_manifest.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "artifacts/nyc_full/events"

    with pytest.raises(ValueError, match="exactly match"):
        write_nyc_events_bundle(
            holiday_path,
            event_path,
            panel_dir,
            data_manifest,
            output,
            project_root=tmp_path,
            config=config,
        )

    assert (output / "NYC_EVENTS_INCOMPLETE.json").is_file()
    assert not (output / "manifest.json").exists()


@pytest.mark.parametrize("bad_entry", [{"bytes": 1}, {"path": "../escape.parquet"}])
def test_event_bundle_rejects_malformed_or_traversing_manifest_entry(
    tmp_path: Path,
    bad_entry: dict[str, object],
) -> None:
    holiday_path, event_path, config = _snapshots(tmp_path)
    panel_dir = tmp_path / "data/nyc_full/panel/zone_time"
    panel_dir.mkdir(parents=True)
    panel_path = panel_dir / "part.parquet"
    panel = _panel(panel_path)
    data_manifest = _data_manifest(tmp_path, panel_path, int(panel["trip_count"].sum()))
    payload = json.loads(data_manifest.read_text(encoding="utf-8"))
    payload["files"].append(bad_entry)
    data_manifest.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "artifacts/nyc_full/events"

    with pytest.raises(ValueError, match="malformed|nonportable"):
        write_nyc_events_bundle(
            holiday_path,
            event_path,
            panel_dir,
            data_manifest,
            output,
            project_root=tmp_path,
            config=config,
        )

    assert (output / "NYC_EVENTS_INCOMPLETE.json").is_file()
    assert not (output / "manifest.json").exists()
