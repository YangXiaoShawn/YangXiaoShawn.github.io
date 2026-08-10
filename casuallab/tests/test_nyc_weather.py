import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from casuallab.data import sha256_file
from casuallab.nyc_weather import (
    WEATHER_EVIDENCE_LABEL,
    NYCWeatherConfig,
    normalize_noaa_daily_weather,
    weather_demand_associations,
    write_nyc_weather_bundle,
)


def _raw_weather(path: Path) -> NYCWeatherConfig:
    frame = pd.DataFrame(
        {
            "STATION": ["USW00094728", "USW00094728"],
            "DATE": ["2024-01-01", "2024-01-02"],
            "AWND": [1.5, None],
            "AWND_ATTRIBUTES": [",,W", ""],
            "PRCP": [0.0, 12.0],
            "PRCP_ATTRIBUTES": [",,W,2400", ",,W,2400"],
            "SNOW": [0.0, 5.0],
            "SNOW_ATTRIBUTES": [",,W,2400", ",,W,2400"],
            "SNWD": [0.0, 0.0],
            "SNWD_ATTRIBUTES": [",,W,2400", ",,W,2400"],
            "TMAX": [8.0, 1.0],
            "TMAX_ATTRIBUTES": [",,W", ",,W"],
            "TMIN": [2.0, -3.0],
            "TMIN_ATTRIBUTES": [",,W", ",,W"],
        }
    )
    frame.to_csv(path, index=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return NYCWeatherConfig(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
        expected_rows=2,
        expected_sha256=digest,
    )


def _panel(path: Path) -> pd.DataFrame:
    rows = []
    for day, base in ((date(2024, 1, 1), 10), (date(2024, 1, 2), 15)):
        for hour in range(24):
            for zone in ("1", "2"):
                rows.append(
                    {
                        "service_date": day,
                        "hour": hour,
                        "zone_id": zone,
                        "trip_count": base + hour + int(zone),
                    }
                )
    frame = pd.DataFrame(rows)
    frame.to_parquet(path, index=False)
    return frame


def _data_manifest(root: Path, panel_path: Path, trip_sum: int) -> Path:
    manifest = root / "data/nyc_full/manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    relative = panel_path.relative_to(root)
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
                        "path": str(relative),
                        "bytes": panel_path.stat().st_size,
                        "sha256": sha256_file(panel_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_normalize_noaa_weather_preserves_measurement_flags_and_definitions(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "weather.csv"
    config = _raw_weather(raw)
    weather = normalize_noaa_daily_weather(raw, config)

    assert list(weather["service_date"]) == [date(2024, 1, 1), date(2024, 1, 2)]
    assert weather["temperature_midrange_c"].tolist() == [5.0, -1.0]
    assert weather["wet_day"].tolist() == [False, True]
    assert weather["snow_day"].tolist() == [False, True]
    assert weather["freezing_day"].tolist() == [False, True]
    assert weather["average_wind_mps"].isna().sum() == 1
    assert set(weather["evidence_label"]) == {WEATHER_EVIDENCE_LABEL}
    assert not weather["causal_claim"].any()


def test_noaa_weather_hash_and_calendar_fail_closed(tmp_path: Path) -> None:
    raw = tmp_path / "weather.csv"
    config = _raw_weather(raw)
    raw.write_text(raw.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        normalize_noaa_daily_weather(raw, config)


def test_weather_demand_associations_are_descriptive_and_conserve_trips(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "weather.csv"
    config = _raw_weather(raw)
    weather = normalize_noaa_daily_weather(raw, config)
    panel_path = tmp_path / "panel.parquet"
    panel = _panel(panel_path)

    daily, hourly, summary = weather_demand_associations(
        [panel_path], weather, config
    )

    assert len(daily) == 2
    assert len(hourly) == 24
    assert summary["causal_claim"] is False
    assert summary["coverage"]["wet_days"] == 1
    assert summary["coverage"]["dry_days"] == 1
    assert summary["conservation"]["daily_trip_sum"] == int(panel["trip_count"].sum())
    assert summary["associations"][
        "wet_minus_dry_mean_daily_published_completed_trips"
    ] > 0
    assert "confounded" in " ".join(summary["limitations"])


def test_weather_bundle_verifies_panel_lineage_and_publishes_atomically(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "data/nyc_weather/raw/noaa.csv"
    raw.parent.mkdir(parents=True)
    config = _raw_weather(raw)
    panel_dir = tmp_path / "data/nyc_full/panel/zone_time"
    panel_dir.mkdir(parents=True)
    panel_path = panel_dir / "part.parquet"
    panel = _panel(panel_path)
    manifest = _data_manifest(tmp_path, panel_path, int(panel["trip_count"].sum()))
    output = tmp_path / "artifacts/nyc_full/weather"

    artifacts = write_nyc_weather_bundle(
        raw,
        panel_dir,
        manifest,
        output,
        project_root=tmp_path,
        config=config,
    )

    assert all(path.is_file() for path in artifacts.paths())
    assert not (output / "NYC_WEATHER_INCOMPLETE.json").exists()
    payload = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    assert payload["evidence_label"] == WEATHER_EVIDENCE_LABEL
    assert payload["checks"]["trip_conservation"] is True
    assert all(not Path(entry["path"]).is_absolute() for entry in payload["files"])


def test_weather_bundle_leaves_marker_when_panel_hash_is_stale(tmp_path: Path) -> None:
    raw = tmp_path / "data/nyc_weather/raw/noaa.csv"
    raw.parent.mkdir(parents=True)
    config = _raw_weather(raw)
    panel_dir = tmp_path / "data/nyc_full/panel/zone_time"
    panel_dir.mkdir(parents=True)
    panel_path = panel_dir / "part.parquet"
    panel = _panel(panel_path)
    manifest = _data_manifest(tmp_path, panel_path, int(panel["trip_count"].sum()))
    panel_path.write_bytes(panel_path.read_bytes() + b"tamper")
    output = tmp_path / "artifacts/nyc_full/weather"

    with pytest.raises(ValueError, match="lineage mismatch"):
        write_nyc_weather_bundle(
            raw,
            panel_dir,
            manifest,
            output,
            project_root=tmp_path,
            config=config,
        )
    assert (output / "NYC_WEATHER_INCOMPLETE.json").is_file()
    assert not (output / "manifest.json").exists()
