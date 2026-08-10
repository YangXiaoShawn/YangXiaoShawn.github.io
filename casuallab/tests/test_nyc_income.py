import json
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import shapefile

from casuallab.data import sha256_file
from casuallab.nyc_income import (
    BIN_ESTIMATE_COLUMNS,
    ESTIMATE_COLUMNS,
    INCOME_EVIDENCE_LABEL,
    MOE_COLUMNS,
    NYCIncomeConfig,
    aggregate_acs_b19001_to_nta,
    allocate_nta_income_to_taxi_zones,
    build_taxi_zone_nta_crosswalk,
    income_trip_descriptions,
    write_nyc_income_bundle,
)


def test_committed_income_sources_match_pins_and_source_manifest() -> None:
    root = Path(__file__).resolve().parents[1]
    raw = root / "data/nyc_income/raw"
    config = NYCIncomeConfig()
    expected = {
        "taxi_zones.zip": config.expected_taxi_sha256,
        "nyc_nta2020.geojson": config.expected_nta_sha256,
        "nyc_tract2020_to_nta2020.csv": config.expected_tract_to_nta_sha256,
        "acs_2022_5yr_b19001_nyc_tracts.dat": config.expected_acs_sha256,
    }
    manifest = json.loads((raw / "source_manifest.json").read_text(encoding="utf-8"))
    entries = {Path(entry["path"]).name: entry for entry in manifest["sources"]}

    assert manifest["causal_claim"] is False
    assert manifest["evidence_label"] == INCOME_EVIDENCE_LABEL
    assert set(entries) == set(expected)
    for filename, digest in expected.items():
        path = raw / filename
        assert path.is_file()
        assert sha256_file(path) == digest == entries[filename]["sha256"]
        assert path.stat().st_size == entries[filename]["bytes"]
        assert entries[filename]["url"].startswith("https://")


def _write_taxi_zip(path: Path) -> None:
    source = path.parent / "taxi_shape"
    source.mkdir(parents=True)
    base = source / "taxi_zones"
    writer = shapefile.Writer(str(base), shapeType=shapefile.POLYGON)
    writer.field("OBJECTID", "N", decimal=0)
    writer.field("Shape_Leng", "F", decimal=6)
    writer.field("Shape_Area", "F", decimal=6)
    writer.field("zone", "C", size=50)
    writer.field("LocationID", "N", decimal=0)
    writer.field("borough", "C", size=30)
    for location_id, left, name in ((1, 0.0, "West"), (2, 1.0, "East")):
        writer.poly(
            [
                [
                    [left, 0.0],
                    [left, 1.0],
                    [left + 1.0, 1.0],
                    [left + 1.0, 0.0],
                    [left, 0.0],
                ]
            ]
        )
        writer.record(location_id, 4.0, 1.0, name, location_id, "Fixture")
    writer.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for suffix in ("shp", "shx", "dbf"):
            archive.write(base.with_suffix(f".{suffix}"), f"taxi_zones/taxi_zones.{suffix}")


def _write_nta(path: Path) -> None:
    features = []
    for code, left, name in (("BX0001", 0.0, "Low NTA"), ("BX0002", 1.0, "High NTA")):
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "nta2020": code,
                    "ntaname": name,
                    "ntatype": "0",
                    "boroname": "Fixture",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [left, 0.0],
                            [left + 1.0, 0.0],
                            [left + 1.0, 1.0],
                            [left, 1.0],
                            [left, 0.0],
                        ]
                    ],
                },
            }
        )
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )


def _write_tract_map(path: Path) -> None:
    pd.DataFrame(
        {
            "geoid": ["36005000100", "36005000200"],
            "nta2020": ["BX0001", "BX0002"],
            "ntaname": ["Low NTA", "High NTA"],
            "borocode": ["2", "2"],
            "boroname": ["Bronx", "Bronx"],
        }
    ).to_csv(path, index=False)


def _acs_row(geoid: str, *, under_10k: int, at_least_100k: int) -> dict[str, int | str]:
    row: dict[str, int | str] = {"GEO_ID": f"1400000US{geoid}"}
    total = under_10k + at_least_100k
    for column in ESTIMATE_COLUMNS:
        row[column] = 0
    for column in MOE_COLUMNS:
        row[column] = 1
    row[ESTIMATE_COLUMNS[0]] = total
    row["B19001_E002"] = under_10k
    row["B19001_E014"] = at_least_100k
    return row


def _write_acs(path: Path) -> None:
    columns = ["GEO_ID"]
    for estimate, moe in zip(ESTIMATE_COLUMNS, MOE_COLUMNS, strict=True):
        columns.extend([estimate, moe])
    pd.DataFrame(
        [
            _acs_row("36005000100", under_10k=60, at_least_100k=40),
            _acs_row("36005000200", under_10k=20, at_least_100k=80),
        ]
    )[columns].to_csv(path, sep="|", index=False)


def _write_panel(path: Path) -> pd.DataFrame:
    rows = []
    for service_date in (date(2024, 1, 1), date(2024, 1, 2)):
        for hour in range(24):
            rows.extend(
                [
                    {
                        "service_date": service_date,
                        "hour": hour,
                        "zone_id": "1",
                        "trip_count": 10,
                    },
                    {
                        "service_date": service_date,
                        "hour": hour,
                        "zone_id": "2",
                        "trip_count": 20,
                    },
                ]
            )
    frame = pd.DataFrame(rows)
    frame.to_parquet(path, index=False)
    return frame


def _write_data_manifest(root: Path, panel_path: Path, trip_sum: int) -> Path:
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


def _fixture(root: Path) -> tuple[dict[str, Path], NYCIncomeConfig]:
    raw = root / "data/nyc_income/raw"
    raw.mkdir(parents=True)
    taxi = raw / "taxi_zones.zip"
    nta = raw / "nta.geojson"
    tract = raw / "tract.csv"
    acs = raw / "acs.dat"
    _write_taxi_zip(taxi)
    _write_nta(nta)
    _write_tract_map(tract)
    _write_acs(acs)
    panel_dir = root / "data/nyc_full/panel/zone_time"
    panel_dir.mkdir(parents=True)
    panel = panel_dir / "part.parquet"
    frame = _write_panel(panel)
    manifest = _write_data_manifest(root, panel, int(frame["trip_count"].sum()))
    config = NYCIncomeConfig(
        expected_taxi_sha256=sha256_file(taxi),
        expected_nta_sha256=sha256_file(nta),
        expected_tract_to_nta_sha256=sha256_file(tract),
        expected_acs_sha256=sha256_file(acs),
        expected_taxi_features=2,
        expected_nta_features=2,
        expected_tract_rows=2,
        expected_acs_rows=2,
        taxi_source_crs="EPSG:4326",
        nta_source_crs="EPSG:4326",
        minimum_residential_nta_area_coverage=0.999,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
    )
    return {
        "taxi": taxi,
        "nta": nta,
        "tract": tract,
        "acs": acs,
        "panel_dir": panel_dir,
        "panel": panel,
        "manifest": manifest,
    }, config


def test_tract_bins_are_aggregated_before_grouped_medians(tmp_path: Path) -> None:
    paths, config = _fixture(tmp_path)
    nta, diagnostics = aggregate_acs_b19001_to_nta(
        paths["tract"],
        paths["acs"],
        ["BX0001", "BX0002"],
        config,
    )

    assert diagnostics["median_of_medians_used"] is False
    assert diagnostics["acs_total_households"] == 200
    assert diagnostics["mapped_total_households"] == 200
    assert int(nta[ESTIMATE_COLUMNS[0]].sum()) == 200
    assert int(nta[list(BIN_ESTIMATE_COLUMNS)].to_numpy().sum()) == 200
    assert set(nta["evidence_label"]) == {INCOME_EVIDENCE_LABEL}
    assert not nta["causal_claim"].any()


def test_equal_area_crosswalk_is_complete_and_normalized(tmp_path: Path) -> None:
    paths, config = _fixture(tmp_path)
    crosswalk, diagnostics = build_taxi_zone_nta_crosswalk(
        paths["taxi"],
        paths["nta"],
        config,
    )

    assert len(crosswalk) == 2
    assert set(crosswalk["location_id"]) == {1, 2}
    assert crosswalk["is_dominant_nta"].all()
    assert crosswalk.groupby("nta2020")["nta_allocation_weight"].sum().eq(1).all()
    assert diagnostics["equal_area_crs"] == "EPSG:6933"
    assert diagnostics["taxi_zones_without_nta_overlap"] == 0


def test_nonresidential_dominant_zone_is_primary_unclassified_but_sensitivity_kept() -> None:
    crosswalk = pd.DataFrame(
        [
            {
                "location_id": 1,
                "taxi_zone_name": "Fixture Airport",
                "taxi_borough": "Fixture",
                "nta2020": "AIR001",
                "nta_name": "Airport",
                "nta_type": "8",
                "taxi_zone_area_m2": 100.0,
                "intersection_area_m2": 90.0,
                "taxi_zone_area_share": 0.9,
                "nta_area_share": 1.0,
                "nta_allocation_weight": 1.0,
                "is_dominant_nta": True,
            },
            {
                "location_id": 1,
                "taxi_zone_name": "Fixture Airport",
                "taxi_borough": "Fixture",
                "nta2020": "RES001",
                "nta_name": "Residential",
                "nta_type": "0",
                "taxi_zone_area_m2": 100.0,
                "intersection_area_m2": 10.0,
                "taxi_zone_area_share": 0.1,
                "nta_area_share": 0.1,
                "nta_allocation_weight": 0.1,
                "is_dominant_nta": False,
            },
            {
                "location_id": 2,
                "taxi_zone_name": "Fixture Residential",
                "taxi_borough": "Fixture",
                "nta2020": "RES001",
                "nta_name": "Residential",
                "nta_type": "0",
                "taxi_zone_area_m2": 90.0,
                "intersection_area_m2": 90.0,
                "taxi_zone_area_share": 1.0,
                "nta_area_share": 0.9,
                "nta_allocation_weight": 0.9,
                "is_dominant_nta": True,
            },
        ]
    )
    rows = []
    for nta2020, total, low, high in (
        ("AIR001", 0, 0, 0),
        ("RES001", 100, 40, 60),
    ):
        row: dict[str, float | str] = {"nta2020": nta2020}
        row.update({column: 0.0 for column in ESTIMATE_COLUMNS})
        row[ESTIMATE_COLUMNS[0]] = float(total)
        row["B19001_E002"] = float(low)
        row["B19001_E014"] = float(high)
        rows.append(row)
    nta_income = pd.DataFrame(rows)

    zones, diagnostics = allocate_nta_income_to_taxi_zones(
        crosswalk,
        nta_income,
        citywide_grouped_median_usd=100_000.0,
        config=NYCIncomeConfig(
            minimum_allocated_households=1.0,
            minimum_residential_taxi_zone_area_share=0.5,
        ),
    )
    indexed = zones.set_index("location_id")

    assert indexed.loc[1, "dominant_nta_type"] == "8"
    assert not bool(indexed.loc[1, "dominant_nta_residential_eligible"])
    assert indexed.loc[1, "residential_taxi_zone_area_share"] == pytest.approx(0.1)
    assert indexed.loc[1, "area_allocated_residential_households"] == pytest.approx(10)
    assert indexed.loc[1, "income_group"] == "unclassified"
    assert (
        indexed.loc[1, "income_group_all_zone_area_allocation_sensitivity"]
        == "high_income_area"
    )
    assert indexed.loc[2, "income_group"] == "high_income_area"
    assert diagnostics["dominant_nonresidential_zone_rows"] == 1
    assert diagnostics[
        "dominant_nonresidential_zones_classified_only_in_sensitivity"
    ] == 1


def test_primary_gate_requires_half_of_taxi_zone_area_to_be_residential() -> None:
    crosswalk_rows = []
    for code, nta_type, area, dominant in (
        ("RES001", "0", 40.0, True),
        ("AIR001", "8", 30.0, False),
        ("PARK01", "9", 30.0, False),
    ):
        crosswalk_rows.append(
            {
                "location_id": 1,
                "taxi_zone_name": "Mixed Special Area",
                "taxi_borough": "Fixture",
                "nta2020": code,
                "nta_name": code,
                "nta_type": nta_type,
                "taxi_zone_area_m2": 100.0,
                "intersection_area_m2": area,
                "taxi_zone_area_share": area / 100.0,
                "nta_area_share": 1.0,
                "nta_allocation_weight": 1.0,
                "is_dominant_nta": dominant,
            }
        )
    nta_rows = []
    for code, total in (("RES001", 100.0), ("AIR001", 0.0), ("PARK01", 0.0)):
        row: dict[str, float | str] = {"nta2020": code}
        row.update({column: 0.0 for column in ESTIMATE_COLUMNS})
        row[ESTIMATE_COLUMNS[0]] = total
        row["B19001_E002"] = total * 0.4
        row["B19001_E014"] = total * 0.6
        nta_rows.append(row)

    zones, diagnostics = allocate_nta_income_to_taxi_zones(
        pd.DataFrame(crosswalk_rows),
        pd.DataFrame(nta_rows),
        citywide_grouped_median_usd=100_000.0,
        config=NYCIncomeConfig(
            minimum_allocated_households=1.0,
            minimum_residential_taxi_zone_area_share=0.5,
        ),
    )
    zone = zones.iloc[0]

    assert zone["dominant_nta_type"] == "0"
    assert bool(zone["dominant_nta_residential_eligible"])
    assert zone["residential_taxi_zone_area_share"] == pytest.approx(0.4)
    assert not bool(zone["primary_income_classification_eligible"])
    assert zone["income_group"] == "unclassified"
    assert zone["income_group_all_zone_area_allocation_sensitivity"] == "high_income_area"
    assert diagnostics["classified_zone_rows"] == 0


def test_trip_summary_counts_only_actual_nonresidential_zones(tmp_path: Path) -> None:
    zone_income = pd.DataFrame(
        {
            "location_id": [1, 2, 3],
            "taxi_zone_name": ["Low", "High", "Airport"],
            "taxi_borough": ["Fixture"] * 3,
            "income_group": [
                "low_income_area",
                "high_income_area",
                "unclassified",
            ],
            "income_group_all_zone_area_allocation_sensitivity": [
                "low_income_area",
                "high_income_area",
                "high_income_area",
            ],
            "primary_income_classification_eligible": [True, True, False],
            "grouped_median_household_income_usd": [50_000.0, 100_000.0, 120_000.0],
            "grouped_median_top_coded": [False, False, False],
            "citywide_grouped_median_threshold_usd": [75_000.0] * 3,
            "nta_covered_area_share": [1.0, 1.0, 1.0],
            "dominant_nta2020": ["RESLOW", "RESHIGH", "AIRPORT"],
            "dominant_nta_name": ["Low", "High", "Airport"],
            "dominant_nta_type": ["0", "0", "8"],
            "dominant_nta_residential_eligible": [True, True, False],
            "residential_intersection_area_m2": [100.0, 100.0, 5.0],
            "residential_taxi_zone_area_share": [1.0, 1.0, 0.05],
            "residential_nta_count": [1, 1, 1],
            "area_allocated_residential_households": [100.0, 100.0, 5.0],
            ESTIMATE_COLUMNS[0]: [100.0, 100.0, 5.0],
        }
    )
    rows = []
    for hour in range(24):
        for location_id, trips in ((1, 10), (2, 20), (3, 30)):
            rows.append(
                {
                    "service_date": date(2024, 1, 1),
                    "hour": hour,
                    "zone_id": str(location_id),
                    "trip_count": trips,
                }
            )
    panel = tmp_path / "panel.parquet"
    pd.DataFrame(rows).to_parquet(panel, index=False)

    _zone, _daily, _monthly, summary = income_trip_descriptions(
        [panel],
        zone_income,
        NYCIncomeConfig(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 1),
        ),
    )

    assert summary["coverage"]["dominant_nonresidential_panel_zones"] == 1
    assert summary["coverage"]["dominant_nonresidential_published_completed_trips"] == 720
    assert summary["conservation"]["primary_nonresidential_classified_zones"] == 0
    sensitivity = summary["sensitivity"]["all_zone_area_allocation"]
    assert sensitivity["dominant_nonresidential_zones_classified"] == 1
    assert sensitivity[
        "dominant_nonresidential_classified_published_completed_trips"
    ] == 720


def test_income_bundle_is_ecological_atomic_portable_and_conserving(tmp_path: Path) -> None:
    paths, config = _fixture(tmp_path)
    output = tmp_path / "artifacts/nyc_full/income"

    artifacts = write_nyc_income_bundle(
        paths["taxi"],
        paths["nta"],
        paths["tract"],
        paths["acs"],
        paths["panel_dir"],
        paths["manifest"],
        output,
        project_root=tmp_path,
        config=config,
    )

    assert all(path.is_file() for path in artifacts.paths())
    assert not (output / "NYC_INCOME_INCOMPLETE.json").exists()
    manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
    assert manifest["evidence_label"] == INCOME_EVIDENCE_LABEL
    assert manifest["causal_claim"] is False
    assert manifest["checks"]["median_of_medians_used"] is False
    assert manifest["checks"]["household_distribution_conserved"] is True
    assert manifest["checks"]["dominant_nonresidential_primary_unclassified"] is True
    assert manifest["checks"]["all_zone_classification_is_sensitivity_only"] is True
    assert all(not Path(entry["path"]).is_absolute() for entry in manifest["files"])
    assert all(not Path(entry["path"]).is_absolute() for entry in manifest["inputs"])
    panel_inputs = [
        entry for entry in manifest["inputs"] if entry["role"] == "nyc_full_zone_time_panel"
    ]
    assert len(panel_inputs) == 1
    assert panel_inputs[0]["path"] == str(paths["panel"].relative_to(tmp_path))
    assert panel_inputs[0]["sha256"] == sha256_file(paths["panel"])
    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["conservation"]["zone_trip_sum"] == 1_440
    assert summary["conservation"]["passes"] is True
    assert summary["coverage"]["classified_trip_coverage"] == 1.0
    assert summary["causal_claim"] is False
    assert summary["conservation"]["primary_nonresidential_classified_zones"] == 0
    assert summary["sensitivity"]["all_zone_area_allocation"]["primary_result"] is False
    assert set(summary["sensitivity"]["all_zone_area_allocation"]["groups"]) == {
        "high_income_area",
        "low_income_area",
        "unclassified",
    }
    assert summary["classification_uncertainty"]["zone_level_margin_of_error_propagated"] is False
    limitations = " ".join(summary["limitations"])
    assert "ecological" in limitations
    assert "Neither income effects" in limitations
    monthly = pd.read_csv(artifacts.monthly_path)
    assert set(monthly["income_group"]) == {"low_income_area", "high_income_area"}
    assert int(monthly["published_completed_trips"].sum()) == 1_440

    paths["panel"].write_bytes(paths["panel"].read_bytes() + b"post-bundle-tamper")
    assert sha256_file(paths["panel"]) != panel_inputs[0]["sha256"]


def test_income_bundle_leaves_marker_on_source_tamper(tmp_path: Path) -> None:
    paths, config = _fixture(tmp_path)
    paths["acs"].write_text(paths["acs"].read_text(encoding="utf-8") + "\n", encoding="utf-8")
    output = tmp_path / "artifacts/nyc_full/income"

    with pytest.raises(ValueError, match="SHA-256"):
        write_nyc_income_bundle(
            paths["taxi"],
            paths["nta"],
            paths["tract"],
            paths["acs"],
            paths["panel_dir"],
            paths["manifest"],
            output,
            project_root=tmp_path,
            config=config,
        )
    assert (output / "NYC_INCOME_INCOMPLETE.json").is_file()
    assert not (output / "manifest.json").exists()


def test_income_bundle_rejects_stale_panel_lineage(tmp_path: Path) -> None:
    paths, config = _fixture(tmp_path)
    paths["panel"].write_bytes(paths["panel"].read_bytes() + b"tamper")
    output = tmp_path / "artifacts/nyc_full/income"

    with pytest.raises(ValueError, match="lineage mismatch"):
        write_nyc_income_bundle(
            paths["taxi"],
            paths["nta"],
            paths["tract"],
            paths["acs"],
            paths["panel_dir"],
            paths["manifest"],
            output,
            project_root=tmp_path,
            config=config,
        )
    assert (output / "NYC_INCOME_INCOMPLETE.json").is_file()
    assert not (output / "manifest.json").exists()


def test_income_bundle_rejects_parent_traversal_in_source_manifest(tmp_path: Path) -> None:
    paths, config = _fixture(tmp_path)
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../outside.parquet"
    paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "artifacts/nyc_full/income"

    with pytest.raises(ValueError, match="must not contain"):
        write_nyc_income_bundle(
            paths["taxi"],
            paths["nta"],
            paths["tract"],
            paths["acs"],
            paths["panel_dir"],
            paths["manifest"],
            output,
            project_root=tmp_path,
            config=config,
        )
    assert (output / "NYC_INCOME_INCOMPLETE.json").is_file()
    assert not (output / "manifest.json").exists()


def test_acs_distribution_total_mismatch_fails_closed(tmp_path: Path) -> None:
    paths, config = _fixture(tmp_path)
    acs = pd.read_csv(paths["acs"], sep="|")
    acs.loc[0, ESTIMATE_COLUMNS[0]] += 1
    acs.to_csv(paths["acs"], sep="|", index=False)
    invalid_config = NYCIncomeConfig(
        expected_taxi_sha256=config.expected_taxi_sha256,
        expected_nta_sha256=config.expected_nta_sha256,
        expected_tract_to_nta_sha256=config.expected_tract_to_nta_sha256,
        expected_acs_sha256=sha256_file(paths["acs"]),
        expected_taxi_features=2,
        expected_nta_features=2,
        expected_tract_rows=2,
        expected_acs_rows=2,
        taxi_source_crs="EPSG:4326",
        nta_source_crs="EPSG:4326",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
    )

    with pytest.raises(ValueError, match="totals"):
        aggregate_acs_b19001_to_nta(
            paths["tract"],
            paths["acs"],
            ["BX0001", "BX0002"],
            invalid_config,
        )
