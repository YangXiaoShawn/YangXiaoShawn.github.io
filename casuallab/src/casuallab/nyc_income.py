"""Auditable NYC taxi-zone income heterogeneity as descriptive evidence.

This module spatially allocates Census ACS ``B19001`` household-income-bin
counts to TLC Taxi Zones.  It never takes medians of tract or NTA medians:
tract bin counts are summed to 2020 NTAs, the complete NTA distribution is
allocated by equal-area polygon overlap, and grouped medians are computed only
after aggregation.  The allocation assumes households are uniformly located
within each NTA, so all trip comparisons are ecological, observational, and
non-causal.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import shapefile
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform
from shapely.strtree import STRtree

from casuallab.data import sha256_file

TAXI_ZONES_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip"
TAXI_ZONES_SHA256 = "f6d711917bb4340f8f644d5366c51665489eb2d426dd1a4a55677721ae5adf17"
NTA2020_URL = (
    "https://data.cityofnewyork.us/resource/9nt8-h7nd.geojson?"
    "$limit=500&$order=nta2020"
)
NTA2020_SHA256 = "4a036c53ce665a73954f260ef4f3a8c49f33d75fb2fc859fe0baf92f4b7f8af8"
TRACT_TO_NTA_URL = (
    "https://data.cityofnewyork.us/resource/63ge-mke6.csv?"
    "$select=geoid,nta2020,ntaname,borocode,boroname&"
    "$where=nta2020%20is%20not%20null&$limit=5000&$order=geoid"
)
TRACT_TO_NTA_SHA256 = (
    "a23087eca9279f0081e6984e53bcd46ea13e2076be63235386d483e91bf7dc96"
)
ACS_B19001_PARENT_URL = (
    "https://www2.census.gov/programs-surveys/acs/summary_file/2022/"
    "table-based-SF/data/5YRData/acsdt5y2022-b19001.dat"
)
ACS_B19001_PARENT_BYTES = 69_201_868
ACS_B19001_PARENT_SHA256 = (
    "3cdb575ba0d2f03fa9f008617504e675577ee3cbe503461de9d80c0c3280fdac"
)
ACS_B19001_NYC_SLICE_SHA256 = (
    "b26ec3e7298e1842d383c8581e11ecbe3fd027e6e09238bd5c67da928bc1c215"
)

INCOME_EVIDENCE_LABEL = "descriptive_observed_external_neighborhood_income"
INCOME_SCHEMA_VERSION = "1.0.0"
NYC_COUNTY_FIPS = ("005", "047", "061", "081", "085")
EQUAL_AREA_CRS = "EPSG:6933"
TAXI_SOURCE_CRS = "EPSG:2263"
NTA_SOURCE_CRS = "EPSG:4326"

# B19001 estimate bins 002--017.  The final bin is open-ended (>= $200,000).
INCOME_BIN_LOWER_USD = (
    0.0,
    10_000.0,
    15_000.0,
    20_000.0,
    25_000.0,
    30_000.0,
    35_000.0,
    40_000.0,
    45_000.0,
    50_000.0,
    60_000.0,
    75_000.0,
    100_000.0,
    125_000.0,
    150_000.0,
    200_000.0,
)
INCOME_BIN_UPPER_USD = (
    10_000.0,
    15_000.0,
    20_000.0,
    25_000.0,
    30_000.0,
    35_000.0,
    40_000.0,
    45_000.0,
    50_000.0,
    60_000.0,
    75_000.0,
    100_000.0,
    125_000.0,
    150_000.0,
    200_000.0,
    None,
)
ESTIMATE_COLUMNS = tuple(f"B19001_E{index:03d}" for index in range(1, 18))
MOE_COLUMNS = tuple(f"B19001_M{index:03d}" for index in range(1, 18))
BIN_ESTIMATE_COLUMNS = ESTIMATE_COLUMNS[1:]
BIN_MOE_COLUMNS = MOE_COLUMNS[1:]


@dataclass(frozen=True, slots=True)
class NYCIncomeConfig:
    """Pinned source, geometry, grouping, and month contract."""

    expected_taxi_sha256: str = TAXI_ZONES_SHA256
    expected_nta_sha256: str = NTA2020_SHA256
    expected_tract_to_nta_sha256: str = TRACT_TO_NTA_SHA256
    expected_acs_sha256: str = ACS_B19001_NYC_SLICE_SHA256
    expected_taxi_features: int = 263
    expected_nta_features: int = 262
    expected_tract_rows: int = 2_325
    expected_acs_rows: int = 2_327
    taxi_source_crs: str = TAXI_SOURCE_CRS
    nta_source_crs: str = NTA_SOURCE_CRS
    equal_area_crs: str = EQUAL_AREA_CRS
    minimum_intersection_area_m2: float = 1.0
    minimum_residential_nta_area_coverage: float = 0.98
    minimum_allocated_households: float = 1.0
    minimum_residential_taxi_zone_area_share: float = 0.5
    residential_nta_type_codes: tuple[str, ...] = ("0",)
    start_date: date = date(2024, 1, 1)
    end_date: date = date(2024, 1, 31)

    def __post_init__(self) -> None:
        for name in (
            "expected_taxi_sha256",
            "expected_nta_sha256",
            "expected_tract_to_nta_sha256",
            "expected_acs_sha256",
        ):
            digest = str(getattr(self, name))
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        for name in (
            "expected_taxi_features",
            "expected_nta_features",
            "expected_tract_rows",
            "expected_acs_rows",
        ):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be positive")
        if self.start_date > self.end_date:
            raise ValueError("income start_date must not exceed end_date")
        if not math.isfinite(self.minimum_intersection_area_m2) or self.minimum_intersection_area_m2 < 0:
            raise ValueError("minimum_intersection_area_m2 must be finite and nonnegative")
        if not 0 < self.minimum_residential_nta_area_coverage <= 1:
            raise ValueError("minimum_residential_nta_area_coverage must be in (0, 1]")
        if not math.isfinite(self.minimum_allocated_households) or self.minimum_allocated_households <= 0:
            raise ValueError("minimum_allocated_households must be finite and positive")
        if not 0 <= self.minimum_residential_taxi_zone_area_share <= 1:
            raise ValueError(
                "minimum_residential_taxi_zone_area_share must be in [0, 1]"
            )
        if (
            not self.residential_nta_type_codes
            or any(not str(code).strip() for code in self.residential_nta_type_codes)
            or len(set(self.residential_nta_type_codes))
            != len(self.residential_nta_type_codes)
        ):
            raise ValueError("residential_nta_type_codes must be unique nonempty strings")


@dataclass(frozen=True, slots=True)
class NYCIncomeArtifacts:
    """Published crosswalk, income summaries, trip descriptions, and manifest."""

    crosswalk_path: Path
    nta_income_path: Path
    zone_income_path: Path
    daily_path: Path
    monthly_path: Path
    summary_path: Path
    manifest_path: Path

    def paths(self) -> tuple[Path, ...]:
        return (
            self.crosswalk_path,
            self.nta_income_path,
            self.zone_income_path,
            self.daily_path,
            self.monthly_path,
            self.summary_path,
            self.manifest_path,
        )


def _require_pinned_file(path: str | Path, expected_sha256: str, role: str) -> Path:
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if sha256_file(source) != expected_sha256:
        raise ValueError(f"{role} SHA-256 does not match the configured pin")
    return source


def _portable(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError as exc:
        raise ValueError(f"income path is outside project_root: {path}") from exc


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _scan_sql(paths: Sequence[Path]) -> str:
    if not paths:
        raise FileNotFoundError("NYC income analysis requires zone-time Parquet files")
    rendered = ", ".join(_sql_string(str(path.resolve())) for path in paths)
    return f"read_parquet([{rendered}], hive_partitioning=false)"


def _atomic_csv(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        prefix=f".{path.stem}-",
        suffix=path.suffix,
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        frame.to_csv(handle, index=False)
    temporary.replace(path)
    return path


def _atomic_json(payload: Mapping[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.stem}-",
        suffix=path.suffix,
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    temporary.replace(path)
    return path


def _finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def _grouped_median(bin_counts: Sequence[float]) -> tuple[float | None, bool]:
    """Return a grouped-distribution median and whether it is top-coded."""

    counts = np.asarray(bin_counts, dtype=float)
    if counts.shape != (16,) or not np.isfinite(counts).all() or (counts < 0).any():
        raise ValueError("B19001 grouped-median counts must be 16 finite nonnegative values")
    total = float(counts.sum())
    if total <= 0:
        return None, False
    rank = 0.5 * total
    cumulative = np.cumsum(counts)
    index = int(np.searchsorted(cumulative, rank, side="left"))
    lower = INCOME_BIN_LOWER_USD[index]
    upper = INCOME_BIN_UPPER_USD[index]
    if upper is None:
        return lower, True
    before = float(cumulative[index - 1]) if index else 0.0
    within = float(counts[index])
    if within <= 0:
        raise ValueError("grouped median selected an empty B19001 bin")
    fraction = min(max((rank - before) / within, 0.0), 1.0)
    return lower + fraction * (upper - lower), False


def _load_taxi_geometries(
    source_path: Path,
    config: NYCIncomeConfig,
) -> list[dict[str, Any]]:
    reader = shapefile.Reader(str(source_path))
    if len(reader) != config.expected_taxi_features:
        raise ValueError("TLC Taxi Zone source has an unexpected feature count")
    transformer = Transformer.from_crs(
        config.taxi_source_crs,
        config.equal_area_crs,
        always_xy=True,
    )
    records: list[dict[str, Any]] = []
    for feature, record in zip(reader.shapes(), reader.records(), strict=True):
        properties = record.as_dict()
        location_id = int(properties["LocationID"])
        geometry = shape(feature.__geo_interface__)
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError(f"TLC Taxi Zone {location_id} has invalid geometry")
        projected = transform(transformer.transform, geometry)
        if projected.is_empty or not projected.is_valid or projected.area <= 0:
            raise ValueError(f"TLC Taxi Zone {location_id} failed equal-area projection")
        records.append(
            {
                "location_id": location_id,
                "taxi_zone_name": str(properties["zone"]),
                "taxi_borough": str(properties["borough"]),
                "geometry": projected,
                "taxi_zone_area_m2": float(projected.area),
            }
        )
    ids = [int(record["location_id"]) for record in records]
    expected_ids = set(range(1, config.expected_taxi_features + 1))
    if len(set(ids)) != len(ids) or set(ids) != expected_ids:
        raise ValueError("TLC Taxi Zone LocationIDs must be unique and calendar-complete")
    return records


def _load_nta_geometries(
    source_path: Path,
    config: NYCIncomeConfig,
) -> list[dict[str, Any]]:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    features = payload.get("features")
    if payload.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ValueError("NTA source must be a GeoJSON FeatureCollection")
    if len(features) != config.expected_nta_features:
        raise ValueError("NTA source has an unexpected feature count")
    transformer = Transformer.from_crs(
        config.nta_source_crs,
        config.equal_area_crs,
        always_xy=True,
    )
    records: list[dict[str, Any]] = []
    for feature in features:
        properties = feature.get("properties", {})
        nta2020 = str(properties.get("nta2020", "")).strip()
        geometry = shape(feature.get("geometry"))
        if not nta2020 or geometry.is_empty or not geometry.is_valid:
            raise ValueError("NTA source contains a missing code or invalid geometry")
        projected = transform(transformer.transform, geometry)
        if projected.is_empty or not projected.is_valid or projected.area <= 0:
            raise ValueError(f"NTA {nta2020} failed equal-area projection")
        records.append(
            {
                "nta2020": nta2020,
                "nta_name": str(properties.get("ntaname", "")),
                "nta_type": str(properties.get("ntatype", "")),
                "nta_borough": str(properties.get("boroname", "")),
                "geometry": projected,
                "nta_area_m2": float(projected.area),
            }
        )
    codes = [str(record["nta2020"]) for record in records]
    if len(set(codes)) != len(codes):
        raise ValueError("NTA2020 codes must be unique")
    return records


def build_taxi_zone_nta_crosswalk(
    taxi_zone_zip_path: str | Path,
    nta_geojson_path: str | Path,
    config: NYCIncomeConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Intersect official polygons in an equal-area CRS and retain full lineage."""

    cfg = config or NYCIncomeConfig()
    taxi_path = _require_pinned_file(
        taxi_zone_zip_path,
        cfg.expected_taxi_sha256,
        "TLC Taxi Zone source",
    )
    nta_path = _require_pinned_file(
        nta_geojson_path,
        cfg.expected_nta_sha256,
        "NYC NTA source",
    )
    taxi_records = _load_taxi_geometries(taxi_path, cfg)
    nta_records = _load_nta_geometries(nta_path, cfg)
    nta_geometries = [record["geometry"] for record in nta_records]
    tree = STRtree(nta_geometries)
    rows: list[dict[str, Any]] = []
    for taxi in taxi_records:
        candidates = tree.query(taxi["geometry"], predicate="intersects")
        matched = False
        for raw_index in candidates:
            nta = nta_records[int(raw_index)]
            area = float(taxi["geometry"].intersection(nta["geometry"]).area)
            if area <= cfg.minimum_intersection_area_m2:
                continue
            matched = True
            rows.append(
                {
                    "location_id": taxi["location_id"],
                    "taxi_zone_name": taxi["taxi_zone_name"],
                    "taxi_borough": taxi["taxi_borough"],
                    "nta2020": nta["nta2020"],
                    "nta_name": nta["nta_name"],
                    "nta_type": nta["nta_type"],
                    "nta_borough": nta["nta_borough"],
                    "taxi_zone_area_m2": taxi["taxi_zone_area_m2"],
                    "nta_area_m2": nta["nta_area_m2"],
                    "intersection_area_m2": area,
                    "has_positive_area_overlap": True,
                }
            )
        if not matched:
            rows.append(
                {
                    "location_id": taxi["location_id"],
                    "taxi_zone_name": taxi["taxi_zone_name"],
                    "taxi_borough": taxi["taxi_borough"],
                    "nta2020": None,
                    "nta_name": None,
                    "nta_type": None,
                    "nta_borough": None,
                    "taxi_zone_area_m2": taxi["taxi_zone_area_m2"],
                    "nta_area_m2": np.nan,
                    "intersection_area_m2": 0.0,
                    "has_positive_area_overlap": False,
                }
            )
    if not rows:
        raise ValueError("Taxi Zone and NTA sources have no positive-area intersections")
    crosswalk = pd.DataFrame(rows)
    crosswalk["taxi_zone_area_share"] = crosswalk["intersection_area_m2"] / crosswalk["taxi_zone_area_m2"]
    crosswalk["nta_area_share"] = (
        crosswalk["intersection_area_m2"] / crosswalk["nta_area_m2"]
    )
    nta_intersection_sum = crosswalk.groupby("nta2020")["intersection_area_m2"].transform("sum")
    crosswalk["nta_allocation_weight"] = (
        crosswalk["intersection_area_m2"] / nta_intersection_sum
    ).fillna(0.0)
    positive = crosswalk["has_positive_area_overlap"]
    dominant_index = crosswalk.loc[positive].groupby("location_id")["intersection_area_m2"].idxmax()
    crosswalk["is_dominant_nta"] = False
    crosswalk.loc[dominant_index, "is_dominant_nta"] = True
    crosswalk["evidence_label"] = INCOME_EVIDENCE_LABEL
    crosswalk["causal_claim"] = False
    crosswalk = crosswalk.sort_values(
        ["location_id", "intersection_area_m2", "nta2020"],
        ascending=[True, False, True],
    ).reset_index(drop=True)

    taxi_coverage = (
        crosswalk.groupby("location_id", as_index=False, dropna=False)
        .agg(
            covered_area_m2=("intersection_area_m2", "sum"),
            taxi_zone_area_m2=("taxi_zone_area_m2", "first"),
        )
    )
    taxi_coverage["coverage"] = (
        taxi_coverage["covered_area_m2"] / taxi_coverage["taxi_zone_area_m2"]
    )
    nta_coverage = (
        crosswalk.loc[positive].groupby("nta2020", as_index=False)
        .agg(
            covered_area_m2=("intersection_area_m2", "sum"),
            nta_area_m2=("nta_area_m2", "first"),
        )
    )
    nta_coverage["coverage"] = nta_coverage["covered_area_m2"] / nta_coverage["nta_area_m2"]
    diagnostics = {
        "taxi_source_features": len(taxi_records),
        "taxi_source_unique_location_ids": len({row["location_id"] for row in taxi_records}),
        "nta_source_features": len(nta_records),
        "crosswalk_rows_including_unmapped_zones": len(crosswalk),
        "positive_area_intersections": int(positive.sum()),
        "taxi_zones_with_nta_overlap": int(crosswalk.loc[positive, "location_id"].nunique()),
        "taxi_zones_without_nta_overlap": int((~positive).sum()),
        "ntas_with_taxi_zone_overlap": int(crosswalk["nta2020"].nunique()),
        "minimum_taxi_zone_area_coverage": float(taxi_coverage["coverage"].min()),
        "median_taxi_zone_area_coverage": float(taxi_coverage["coverage"].median()),
        "minimum_nta_area_coverage": float(nta_coverage["coverage"].min()),
        "median_nta_area_coverage": float(nta_coverage["coverage"].median()),
        "equal_area_crs": cfg.equal_area_crs,
        "minimum_intersection_area_m2": cfg.minimum_intersection_area_m2,
    }
    return crosswalk, diagnostics


def aggregate_acs_b19001_to_nta(
    tract_to_nta_path: str | Path,
    acs_b19001_path: str | Path,
    nta_codes: Sequence[str],
    config: NYCIncomeConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Aggregate tract B19001 counts to NTAs before calculating any median."""

    cfg = config or NYCIncomeConfig()
    tract_path = _require_pinned_file(
        tract_to_nta_path,
        cfg.expected_tract_to_nta_sha256,
        "NYC tract-to-NTA source",
    )
    acs_path = _require_pinned_file(
        acs_b19001_path,
        cfg.expected_acs_sha256,
        "Census ACS B19001 source",
    )
    tract_map = pd.read_csv(tract_path, dtype="string")
    required_map = {"geoid", "nta2020", "ntaname", "borocode", "boroname"}
    if required_map.difference(tract_map.columns):
        raise ValueError("tract-to-NTA source is missing required fields")
    if len(tract_map) != cfg.expected_tract_rows:
        raise ValueError("tract-to-NTA source has an unexpected row count")
    if tract_map["geoid"].isna().any() or tract_map["geoid"].duplicated().any():
        raise ValueError("tract-to-NTA GEOIDs must be nonmissing and unique")
    if not tract_map["geoid"].str.fullmatch(r"36\d{9}").all():
        raise ValueError("tract-to-NTA source contains an invalid New York GEOID")
    if tract_map["nta2020"].isna().any():
        raise ValueError("tract-to-NTA source contains a missing NTA code")

    acs = pd.read_csv(acs_path, sep="|", dtype={"GEO_ID": "string"})
    required_acs = {"GEO_ID", *ESTIMATE_COLUMNS, *MOE_COLUMNS}
    if required_acs.difference(acs.columns):
        raise ValueError("ACS B19001 source is missing estimates or margins of error")
    if len(acs) != cfg.expected_acs_rows:
        raise ValueError("ACS B19001 source has an unexpected row count")
    if acs["GEO_ID"].isna().any() or acs["GEO_ID"].duplicated().any():
        raise ValueError("ACS B19001 GEO_ID values must be nonmissing and unique")
    pattern = re.compile(r"^1400000US36(?:005|047|061|081|085)\d{6}$")
    if not acs["GEO_ID"].astype(str).map(lambda value: bool(pattern.fullmatch(value))).all():
        raise ValueError("ACS slice must contain only NYC Census tracts")
    numeric_columns = [*ESTIMATE_COLUMNS, *MOE_COLUMNS]
    acs[numeric_columns] = acs[numeric_columns].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(acs[numeric_columns].to_numpy(dtype=float)).all():
        raise ValueError("ACS B19001 contains non-finite estimates or margins of error")
    if (acs[numeric_columns] < 0).any().any():
        raise ValueError("ACS B19001 contains negative estimates or margins of error")
    if not (
        acs[ESTIMATE_COLUMNS[0]].to_numpy(dtype=int)
        == acs[list(BIN_ESTIMATE_COLUMNS)].sum(axis=1).to_numpy(dtype=int)
    ).all():
        raise ValueError("ACS B19001 totals do not equal the sixteen income bins")

    acs["geoid"] = acs["GEO_ID"].str.removeprefix("1400000US")
    merged = acs.merge(
        tract_map[["geoid", "nta2020", "ntaname", "boroname"]],
        on="geoid",
        how="left",
        validate="1:1",
        indicator=True,
    )
    missing_map = merged["_merge"] != "both"
    unmatched_households = int(merged.loc[missing_map, ESTIMATE_COLUMNS[0]].sum())
    if unmatched_households != 0:
        raise ValueError("ACS tracts omitted by the clipped NYC crosswalk contain households")
    if not set(tract_map["geoid"]).issubset(set(acs["geoid"])):
        raise ValueError("tract-to-NTA source contains GEOIDs absent from ACS")
    known_nta_codes = {str(code) for code in nta_codes}
    if not set(tract_map["nta2020"]).issubset(known_nta_codes):
        raise ValueError("tract-to-NTA source references an NTA absent from geometry")

    mapped = merged.loc[~missing_map].copy()
    estimates = mapped.groupby("nta2020", as_index=False)[list(ESTIMATE_COLUMNS)].sum()
    moe_squared = mapped[list(MOE_COLUMNS)].astype(float).pow(2)
    moe_squared["nta2020"] = mapped["nta2020"].to_numpy()
    moes = moe_squared.groupby("nta2020", as_index=False)[list(MOE_COLUMNS)].sum()
    moes[list(MOE_COLUMNS)] = np.sqrt(moes[list(MOE_COLUMNS)])
    names = (
        mapped.groupby("nta2020", as_index=False)
        .agg(nta_name=("ntaname", "first"), nta_borough=("boroname", "first"))
    )
    nta = names.merge(estimates, on="nta2020", validate="1:1").merge(
        moes,
        on="nta2020",
        validate="1:1",
    )
    medians = nta[list(BIN_ESTIMATE_COLUMNS)].apply(
        lambda row: _grouped_median(row.to_numpy(dtype=float)),
        axis=1,
    )
    nta["grouped_median_household_income_usd"] = [value[0] for value in medians]
    nta["grouped_median_top_coded"] = [value[1] for value in medians]
    total = nta[ESTIMATE_COLUMNS[0]].astype(float)
    nta["share_households_under_50k"] = (
        nta[list(ESTIMATE_COLUMNS[1:10])].sum(axis=1) / total.replace(0, np.nan)
    )
    nta["share_households_100k_plus"] = (
        nta[list(ESTIMATE_COLUMNS[13:])].sum(axis=1) / total.replace(0, np.nan)
    )
    nta["evidence_label"] = INCOME_EVIDENCE_LABEL
    nta["causal_claim"] = False
    nta = nta.sort_values("nta2020").reset_index(drop=True)

    citywide_counts = nta[list(BIN_ESTIMATE_COLUMNS)].sum(axis=0).to_numpy(dtype=float)
    citywide_median, citywide_top_coded = _grouped_median(citywide_counts)
    if citywide_median is None or citywide_top_coded:
        raise ValueError("citywide grouped median must be finite and below the open top bin")
    diagnostics = {
        "acs_tract_rows": len(acs),
        "mapped_tract_rows": len(mapped),
        "unmatched_zero_household_tract_rows": int(missing_map.sum()),
        "unmatched_households": unmatched_households,
        "nta_rows_with_acs_tracts": len(nta),
        "acs_total_households": int(acs[ESTIMATE_COLUMNS[0]].sum()),
        "mapped_total_households": int(nta[ESTIMATE_COLUMNS[0]].sum()),
        "citywide_grouped_median_household_income_usd": citywide_median,
        "citywide_grouped_median_top_coded": citywide_top_coded,
        "totals_equal_sum_of_bins": True,
        "median_of_medians_used": False,
        "nta_moe_aggregation": "root_sum_of_squares approximation across tracts",
    }
    return nta, diagnostics


def allocate_nta_income_to_taxi_zones(
    crosswalk: pd.DataFrame,
    nta_income: pd.DataFrame,
    citywide_grouped_median_usd: float,
    config: NYCIncomeConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Allocate complete NTA income-bin distributions by normalized area overlap."""

    cfg = config or NYCIncomeConfig()
    required_crosswalk = {
        "location_id",
        "taxi_zone_name",
        "taxi_borough",
        "nta2020",
        "nta_type",
        "nta_area_share",
        "nta_allocation_weight",
        "taxi_zone_area_share",
        "intersection_area_m2",
        "is_dominant_nta",
    }
    if required_crosswalk.difference(crosswalk.columns):
        raise ValueError("Taxi Zone-NTA crosswalk is missing allocation fields")
    required_income = {"nta2020", *ESTIMATE_COLUMNS}
    if required_income.difference(nta_income.columns):
        raise ValueError("NTA income summary is missing B19001 counts")
    merged = crosswalk.merge(
        nta_income[["nta2020", *ESTIMATE_COLUMNS]],
        on="nta2020",
        how="left",
        validate="m:1",
    )
    merged[list(ESTIMATE_COLUMNS)] = merged[list(ESTIMATE_COLUMNS)].fillna(0.0)
    residential_types = {str(code) for code in cfg.residential_nta_type_codes}
    merged["residential_nta_eligible"] = merged["nta_type"].astype("string").isin(
        residential_types
    )
    residential = merged[ESTIMATE_COLUMNS[0]] > 0
    residential_coverage = (
        merged.loc[residential]
        .groupby("nta2020", as_index=False)
        .agg(coverage=("nta_area_share", "sum"))
    )
    if residential_coverage.empty:
        raise ValueError("no household-bearing NTA intersects a Taxi Zone")
    if (
        residential_coverage["coverage"]
        < cfg.minimum_residential_nta_area_coverage
    ).any():
        raise ValueError("a household-bearing NTA lacks sufficient Taxi Zone area coverage")
    allocation_sums = merged.groupby("nta2020")["nta_allocation_weight"].sum()
    if not np.allclose(allocation_sums.to_numpy(dtype=float), 1.0, rtol=0, atol=1e-10):
        raise ValueError("NTA allocation weights do not sum to one")

    allocated_columns: list[str] = []
    for column in ESTIMATE_COLUMNS:
        allocated = f"allocated_{column}"
        merged[allocated] = (
            merged[column].astype(float) * merged["nta_allocation_weight"].astype(float)
        )
        allocated_columns.append(allocated)
    merged["area_allocated_residential_households"] = np.where(
        merged["residential_nta_eligible"],
        merged[f"allocated_{ESTIMATE_COLUMNS[0]}"],
        0.0,
    )
    zone_counts = merged.groupby("location_id", as_index=False)[allocated_columns].sum()
    renamed = {allocated: original for allocated, original in zip(allocated_columns, ESTIMATE_COLUMNS, strict=True)}
    zone_counts = zone_counts.rename(columns=renamed)
    zone_meta = (
        crosswalk.groupby("location_id", as_index=False)
        .agg(
            taxi_zone_name=("taxi_zone_name", "first"),
            taxi_borough=("taxi_borough", "first"),
            taxi_zone_area_m2=("taxi_zone_area_m2", "first"),
            nta_covered_area_share=("taxi_zone_area_share", "sum"),
            intersecting_ntas=("nta2020", "nunique"),
        )
    )
    residential_overlap = (
        merged.loc[merged["residential_nta_eligible"]]
        .groupby("location_id", as_index=False)
        .agg(
            residential_intersection_area_m2=("intersection_area_m2", "sum"),
            residential_taxi_zone_area_share=("taxi_zone_area_share", "sum"),
            residential_nta_count=("nta2020", "nunique"),
            area_allocated_residential_households=(
                "area_allocated_residential_households",
                "sum",
            ),
        )
    )
    dominant = (
        crosswalk.loc[
            crosswalk["is_dominant_nta"],
            ["location_id", "nta2020", "nta_name", "nta_type"],
        ]
        .rename(
            columns={
                "nta2020": "dominant_nta2020",
                "nta_name": "dominant_nta_name",
                "nta_type": "dominant_nta_type",
            }
        )
    )
    zones = (
        zone_meta.merge(dominant, on="location_id", how="left", validate="1:1")
        .merge(residential_overlap, on="location_id", how="left", validate="1:1")
        .merge(
            zone_counts,
            on="location_id",
            how="left",
            validate="1:1",
        )
    )
    for column in (
        "residential_intersection_area_m2",
        "residential_taxi_zone_area_share",
        "residential_nta_count",
        "area_allocated_residential_households",
    ):
        zones[column] = zones[column].fillna(0.0)
    zones["residential_nta_count"] = zones["residential_nta_count"].astype(int)
    zones["dominant_nta_type"] = zones["dominant_nta_type"].astype("string")
    zones["dominant_nta_residential_eligible"] = zones["dominant_nta_type"].isin(
        residential_types
    )
    medians = zones[list(BIN_ESTIMATE_COLUMNS)].apply(
        lambda row: _grouped_median(row.to_numpy(dtype=float)),
        axis=1,
    )
    zones["grouped_median_household_income_usd"] = [value[0] for value in medians]
    zones["grouped_median_top_coded"] = [value[1] for value in medians]
    total = zones[ESTIMATE_COLUMNS[0]].astype(float)
    zones["share_households_under_50k"] = (
        zones[list(ESTIMATE_COLUMNS[1:10])].sum(axis=1) / total.replace(0, np.nan)
    )
    zones["share_households_100k_plus"] = (
        zones[list(ESTIMATE_COLUMNS[13:])].sum(axis=1) / total.replace(0, np.nan)
    )
    zones["citywide_grouped_median_threshold_usd"] = citywide_grouped_median_usd
    zones["grouped_median_distance_from_citywide_threshold_usd"] = (
        zones["grouped_median_household_income_usd"] - citywide_grouped_median_usd
    )
    zones["absolute_grouped_median_distance_from_citywide_threshold_usd"] = zones[
        "grouped_median_distance_from_citywide_threshold_usd"
    ].abs()
    sensitivity_classified = (
        zones[ESTIMATE_COLUMNS[0]] >= cfg.minimum_allocated_households
    ) & zones["grouped_median_household_income_usd"].notna()
    zones["income_group_all_zone_area_allocation_sensitivity"] = "unclassified"
    zones.loc[
        sensitivity_classified
        & (
            zones["grouped_median_household_income_usd"]
            < citywide_grouped_median_usd
        ),
        "income_group_all_zone_area_allocation_sensitivity",
    ] = "low_income_area"
    zones.loc[
        sensitivity_classified
        & (
            zones["grouped_median_household_income_usd"]
            >= citywide_grouped_median_usd
        ),
        "income_group_all_zone_area_allocation_sensitivity",
    ] = "high_income_area"
    zones["primary_income_classification_eligible"] = (
        sensitivity_classified
        & zones["dominant_nta_residential_eligible"]
        & (
            zones["residential_taxi_zone_area_share"]
            >= cfg.minimum_residential_taxi_zone_area_share
        )
    )
    zones["income_group"] = np.where(
        zones["primary_income_classification_eligible"],
        zones["income_group_all_zone_area_allocation_sensitivity"],
        "unclassified",
    )
    zones["evidence_label"] = INCOME_EVIDENCE_LABEL
    zones["causal_claim"] = False
    zones = zones.sort_values("location_id").reset_index(drop=True)

    source_households = float(nta_income[ESTIMATE_COLUMNS[0]].sum())
    allocated_households = float(zones[ESTIMATE_COLUMNS[0]].sum())
    source_bins = nta_income[list(BIN_ESTIMATE_COLUMNS)].sum(axis=0).to_numpy(dtype=float)
    allocated_bins = zones[list(BIN_ESTIMATE_COLUMNS)].sum(axis=0).to_numpy(dtype=float)
    if not math.isclose(source_households, allocated_households, rel_tol=0, abs_tol=1e-6):
        raise ValueError("area allocation does not conserve ACS households")
    if not np.allclose(source_bins, allocated_bins, rtol=0, atol=1e-6):
        raise ValueError("area allocation does not conserve ACS income-bin counts")
    diagnostics = {
        "zone_rows": len(zones),
        "classified_zone_rows": int((zones["income_group"] != "unclassified").sum()),
        "low_income_zone_rows": int((zones["income_group"] == "low_income_area").sum()),
        "high_income_zone_rows": int((zones["income_group"] == "high_income_area").sum()),
        "unclassified_zone_rows": int((zones["income_group"] == "unclassified").sum()),
        "sensitivity_classified_zone_rows": int(
            (
                zones["income_group_all_zone_area_allocation_sensitivity"]
                != "unclassified"
            ).sum()
        ),
        "sensitivity_low_income_zone_rows": int(
            (
                zones["income_group_all_zone_area_allocation_sensitivity"]
                == "low_income_area"
            ).sum()
        ),
        "sensitivity_high_income_zone_rows": int(
            (
                zones["income_group_all_zone_area_allocation_sensitivity"]
                == "high_income_area"
            ).sum()
        ),
        "dominant_nonresidential_zone_rows": int(
            (
                zones["dominant_nta_type"].notna()
                & ~zones["dominant_nta_residential_eligible"]
            ).sum()
        ),
        "dominant_nonresidential_zones_classified_only_in_sensitivity": int(
            (
                zones["dominant_nta_type"].notna()
                & ~zones["dominant_nta_residential_eligible"]
                & (
                    zones["income_group_all_zone_area_allocation_sensitivity"]
                    != "unclassified"
                )
            ).sum()
        ),
        "residential_nta_type_codes": sorted(residential_types),
        "minimum_allocated_households": cfg.minimum_allocated_households,
        "minimum_residential_taxi_zone_area_share": (
            cfg.minimum_residential_taxi_zone_area_share
        ),
        "minimum_primary_classified_residential_taxi_zone_area_share": (
            float(
                zones.loc[
                    zones["primary_income_classification_eligible"],
                    "residential_taxi_zone_area_share",
                ].min()
            )
            if zones["primary_income_classification_eligible"].any()
            else None
        ),
        "minimum_primary_classified_allocated_households": (
            float(
                zones.loc[
                    zones["primary_income_classification_eligible"],
                    ESTIMATE_COLUMNS[0],
                ].min()
            )
            if zones["primary_income_classification_eligible"].any()
            else None
        ),
        "primary_eligibility_rule": (
            "dominant NTA type is pre-specified residential and allocated "
            "households and residential Taxi Zone area share meet configured minima"
        ),
        "source_nta_households": source_households,
        "allocated_taxi_zone_households": allocated_households,
        "households_conserved": True,
        "all_sixteen_bins_conserved": True,
        "minimum_household_nta_area_coverage": float(residential_coverage["coverage"].min()),
        "allocation_assumption": "households are uniformly distributed within each NTA",
        "median_of_medians_used": False,
    }
    return zones, diagnostics


def income_trip_descriptions(
    zone_time_paths: Sequence[str | Path],
    zone_income: pd.DataFrame,
    config: NYCIncomeConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Describe published trips by ecological high/low-income area group."""

    cfg = config or NYCIncomeConfig()
    paths = tuple(Path(path).resolve() for path in zone_time_paths)
    required_zone = {
        "location_id",
        "taxi_zone_name",
        "taxi_borough",
        "income_group",
        "income_group_all_zone_area_allocation_sensitivity",
        "primary_income_classification_eligible",
        "grouped_median_household_income_usd",
        "grouped_median_top_coded",
        "citywide_grouped_median_threshold_usd",
        "nta_covered_area_share",
        "dominant_nta2020",
        "dominant_nta_name",
        "dominant_nta_type",
        "dominant_nta_residential_eligible",
        "residential_intersection_area_m2",
        "residential_taxi_zone_area_share",
        "residential_nta_count",
        "area_allocated_residential_households",
        ESTIMATE_COLUMNS[0],
    }
    if required_zone.difference(zone_income.columns):
        raise ValueError("Taxi Zone income profile is missing required fields")
    if zone_income["location_id"].duplicated().any():
        raise ValueError("Taxi Zone income profile must be unique by LocationID")
    allowed_groups = {"low_income_area", "high_income_area", "unclassified"}
    if not set(zone_income["income_group"]).issubset(allowed_groups):
        raise ValueError("Taxi Zone income profile contains an unknown group")

    connection = duckdb.connect(database=":memory:")
    try:
        daily_zone = connection.execute(
            f"""
            SELECT CAST(zone_id AS VARCHAR) AS panel_zone_id,
                   CAST(service_date AS DATE) AS service_date,
                   COUNT(*)::BIGINT AS zone_hours,
                   SUM(CASE WHEN trip_count > 0 THEN 1 ELSE 0 END)::BIGINT
                       AS occupied_zone_hours,
                   SUM(CAST(trip_count AS BIGINT))::BIGINT
                       AS published_completed_trips
            FROM {_scan_sql(paths)}
            GROUP BY 1, 2
            ORDER BY 2, 1
            """
        ).fetchdf()
    finally:
        connection.close()
    if daily_zone.empty:
        raise ValueError("NYC zone-time panel produced no income-analysis rows")
    daily_zone["service_date"] = pd.to_datetime(
        daily_zone["service_date"],
        errors="raise",
    ).dt.date
    expected_dates = set(pd.date_range(cfg.start_date, cfg.end_date, freq="D").date)
    observed_dates = set(daily_zone["service_date"])
    if observed_dates != expected_dates:
        raise ValueError("NYC income panel does not cover the configured calendar")
    daily_zone["numeric_location_id"] = pd.to_numeric(
        daily_zone["panel_zone_id"],
        errors="coerce",
    ).astype("Int64")
    profile_columns = [
        "location_id",
        "taxi_zone_name",
        "taxi_borough",
        "income_group",
        "income_group_all_zone_area_allocation_sensitivity",
        "primary_income_classification_eligible",
        "grouped_median_household_income_usd",
        "grouped_median_top_coded",
        "citywide_grouped_median_threshold_usd",
        "nta_covered_area_share",
        "dominant_nta2020",
        "dominant_nta_name",
        "dominant_nta_type",
        "dominant_nta_residential_eligible",
        "residential_intersection_area_m2",
        "residential_taxi_zone_area_share",
        "residential_nta_count",
        "area_allocated_residential_households",
        ESTIMATE_COLUMNS[0],
    ]
    profile = zone_income[profile_columns].copy()
    profile["location_id"] = profile["location_id"].astype("Int64")
    joined = daily_zone.merge(
        profile,
        left_on="numeric_location_id",
        right_on="location_id",
        how="left",
        validate="m:1",
    )
    joined["official_taxi_zone"] = joined["location_id"].notna()
    joined["income_group"] = joined["income_group"].fillna("unclassified")
    sensitivity_group_column = "income_group_all_zone_area_allocation_sensitivity"
    joined[sensitivity_group_column] = joined[sensitivity_group_column].fillna(
        "unclassified"
    )
    joined["evidence_label"] = INCOME_EVIDENCE_LABEL
    joined["causal_claim"] = False

    daily = (
        joined.groupby(["service_date", "income_group"], as_index=False, observed=True)
        .agg(
            panel_zones=("panel_zone_id", "nunique"),
            zone_hours=("zone_hours", "sum"),
            occupied_zone_hours=("occupied_zone_hours", "sum"),
            published_completed_trips=("published_completed_trips", "sum"),
        )
        .sort_values(["service_date", "income_group"])
        .reset_index(drop=True)
    )
    daily["mean_published_completed_trips_per_zone_hour"] = (
        daily["published_completed_trips"] / daily["zone_hours"]
    )
    daily["evidence_label"] = INCOME_EVIDENCE_LABEL
    daily["causal_claim"] = False

    monthly = (
        joined.groupby("income_group", as_index=False, observed=True)
        .agg(
            panel_zones=("panel_zone_id", "nunique"),
            observed_days=("service_date", "nunique"),
            zone_hours=("zone_hours", "sum"),
            occupied_zone_hours=("occupied_zone_hours", "sum"),
            published_completed_trips=("published_completed_trips", "sum"),
        )
        .sort_values("income_group")
        .reset_index(drop=True)
    )
    trip_total = float(monthly["published_completed_trips"].sum())
    classified_total = float(
        monthly.loc[
            monthly["income_group"].isin({"low_income_area", "high_income_area"}),
            "published_completed_trips",
        ].sum()
    )
    monthly["mean_published_completed_trips_per_zone_hour"] = (
        monthly["published_completed_trips"] / monthly["zone_hours"]
    )
    monthly["mean_daily_published_completed_trips"] = (
        monthly["published_completed_trips"] / monthly["observed_days"]
    )
    monthly["share_of_all_published_completed_trips"] = (
        monthly["published_completed_trips"] / trip_total
    )
    monthly["share_of_classified_published_completed_trips"] = np.where(
        monthly["income_group"].isin({"low_income_area", "high_income_area"})
        & (classified_total > 0),
        monthly["published_completed_trips"] / classified_total,
        np.nan,
    )
    monthly["evidence_label"] = INCOME_EVIDENCE_LABEL
    monthly["causal_claim"] = False

    sensitivity_monthly = (
        joined.groupby(sensitivity_group_column, as_index=False, observed=True)
        .agg(
            panel_zones=("panel_zone_id", "nunique"),
            observed_days=("service_date", "nunique"),
            zone_hours=("zone_hours", "sum"),
            published_completed_trips=("published_completed_trips", "sum"),
        )
        .sort_values(sensitivity_group_column)
        .reset_index(drop=True)
    )
    sensitivity_monthly["mean_published_completed_trips_per_zone_hour"] = (
        sensitivity_monthly["published_completed_trips"]
        / sensitivity_monthly["zone_hours"]
    )

    observed_zone = (
        joined.groupby("panel_zone_id", as_index=False, dropna=False)
        .agg(
            panel_days=("service_date", "nunique"),
            zone_hours=("zone_hours", "sum"),
            occupied_zone_hours=("occupied_zone_hours", "sum"),
            published_completed_trips=("published_completed_trips", "sum"),
        )
    )
    profile_for_output = zone_income.copy()
    profile_for_output["panel_zone_id"] = profile_for_output["location_id"].astype(str)
    zone_summary = profile_for_output.merge(
        observed_zone,
        on="panel_zone_id",
        how="outer",
        validate="1:1",
        indicator=True,
    )
    zone_summary["official_taxi_zone"] = zone_summary["_merge"] != "right_only"
    zone_summary["observed_in_panel"] = zone_summary["_merge"] != "left_only"
    zone_summary = zone_summary.drop(columns="_merge")
    zone_summary["income_group"] = zone_summary["income_group"].fillna("unclassified")
    zone_summary[sensitivity_group_column] = zone_summary[
        sensitivity_group_column
    ].fillna("unclassified")
    for column in (
        "primary_income_classification_eligible",
        "dominant_nta_residential_eligible",
    ):
        zone_summary[column] = (
            zone_summary[column].astype("boolean").fillna(False).astype(bool)
        )
    for column in (
        "residential_intersection_area_m2",
        "residential_taxi_zone_area_share",
        "area_allocated_residential_households",
    ):
        zone_summary[column] = zone_summary[column].fillna(0)
    zone_summary["residential_nta_count"] = (
        zone_summary["residential_nta_count"].fillna(0).astype(int)
    )
    for column in (
        "panel_days",
        "zone_hours",
        "occupied_zone_hours",
        "published_completed_trips",
    ):
        zone_summary[column] = zone_summary[column].fillna(0).astype(int)
    zone_summary["mean_daily_published_completed_trips"] = (
        zone_summary["published_completed_trips"]
        / zone_summary["panel_days"].replace(0, np.nan)
    )
    zone_summary["mean_published_completed_trips_per_zone_hour"] = (
        zone_summary["published_completed_trips"]
        / zone_summary["zone_hours"].replace(0, np.nan)
    )
    zone_summary["share_of_all_published_completed_trips"] = (
        zone_summary["published_completed_trips"] / trip_total
    )
    zone_summary["evidence_label"] = INCOME_EVIDENCE_LABEL
    zone_summary["causal_claim"] = False
    zone_summary = zone_summary.sort_values(
        "panel_zone_id",
        key=lambda series: pd.to_numeric(series, errors="coerce"),
    ).reset_index(drop=True)

    indexed = monthly.set_index("income_group")
    for required_group in ("low_income_area", "high_income_area"):
        if required_group not in indexed.index:
            raise ValueError("NYC income panel lacks a required high/low-income group")
    low_rate = float(
        indexed.loc["low_income_area", "mean_published_completed_trips_per_zone_hour"]
    )
    high_rate = float(
        indexed.loc["high_income_area", "mean_published_completed_trips_per_zone_hour"]
    )
    classified_trips = int(
        joined.loc[
            joined["income_group"].isin({"low_income_area", "high_income_area"}),
            "published_completed_trips",
        ].sum()
    )
    sensitivity_indexed = sensitivity_monthly.set_index(sensitivity_group_column)
    for required_group in ("low_income_area", "high_income_area"):
        if required_group not in sensitivity_indexed.index:
            raise ValueError("NYC income sensitivity lacks a required high/low-income group")
    sensitivity_low_rate = float(
        sensitivity_indexed.loc[
            "low_income_area",
            "mean_published_completed_trips_per_zone_hour",
        ]
    )
    sensitivity_high_rate = float(
        sensitivity_indexed.loc[
            "high_income_area",
            "mean_published_completed_trips_per_zone_hour",
        ]
    )
    sensitivity_classified = joined[sensitivity_group_column].isin(
        {"low_income_area", "high_income_area"}
    )
    sensitivity_classified_trips = int(
        joined.loc[sensitivity_classified, "published_completed_trips"].sum()
    )
    primary_eligible = (
        joined["primary_income_classification_eligible"]
        .astype("boolean")
        .fillna(False)
        .astype(bool)
    )
    dominant_residential_eligible = (
        joined["dominant_nta_residential_eligible"]
        .astype("boolean")
        .fillna(False)
        .astype(bool)
    )
    dominant_nonresidential = (
        joined["dominant_nta_type"].notna()
        & ~dominant_residential_eligible
    )
    sensitivity_nonresidential_classified = (
        dominant_nonresidential & sensitivity_classified
    )
    primary_classified = joined["income_group"].isin(
        {"low_income_area", "high_income_area"}
    )
    if (primary_classified & ~primary_eligible).any():
        raise ValueError("primary income classification contains an ineligible Taxi Zone")
    if (primary_classified & dominant_nonresidential).any():
        raise ValueError("primary income classification contains a non-residential Taxi Zone")

    primary_groups: dict[str, dict[str, float | int | None]] = {}
    for group in ("high_income_area", "low_income_area", "unclassified"):
        if group in indexed.index:
            row = indexed.loc[group]
            group_trips = int(row["published_completed_trips"])
            primary_groups[group] = {
                "panel_zones": int(row["panel_zones"]),
                "published_completed_trips": group_trips,
                "share_of_all_published_completed_trips": group_trips / trip_total,
                "mean_published_completed_trips_per_zone_hour": _finite_or_none(
                    float(row["mean_published_completed_trips_per_zone_hour"])
                ),
            }
        else:
            primary_groups[group] = {
                "panel_zones": 0,
                "published_completed_trips": 0,
                "share_of_all_published_completed_trips": 0.0,
                "mean_published_completed_trips_per_zone_hour": None,
            }

    sensitivity_groups: dict[str, dict[str, float | int | None]] = {}
    for group in ("high_income_area", "low_income_area", "unclassified"):
        if group in sensitivity_indexed.index:
            row = sensitivity_indexed.loc[group]
            group_trips = int(row["published_completed_trips"])
            group_rate = _finite_or_none(
                float(row["mean_published_completed_trips_per_zone_hour"])
            )
            sensitivity_groups[group] = {
                "panel_zones": int(row["panel_zones"]),
                "published_completed_trips": group_trips,
                "share_of_all_published_completed_trips": group_trips / trip_total,
                "mean_published_completed_trips_per_zone_hour": group_rate,
            }
        else:
            sensitivity_groups[group] = {
                "panel_zones": 0,
                "published_completed_trips": 0,
                "share_of_all_published_completed_trips": 0.0,
                "mean_published_completed_trips_per_zone_hour": None,
            }

    grouped_median_distance = (
        joined["grouped_median_household_income_usd"]
        - joined["citywide_grouped_median_threshold_usd"]
    ).abs()
    threshold_proximity: dict[str, dict[str, float | int]] = {}
    for threshold_usd in (1_000, 2_500, 5_000, 10_000):
        near_threshold = primary_eligible & grouped_median_distance.le(threshold_usd)
        near_trips = int(joined.loc[near_threshold, "published_completed_trips"].sum())
        threshold_proximity[f"within_{threshold_usd}_usd"] = {
            "primary_eligible_panel_zones": int(
                joined.loc[near_threshold, "panel_zone_id"].nunique()
            ),
            "published_completed_trips": near_trips,
            "share_of_primary_classified_trips": (
                near_trips / classified_trips if classified_trips else 0.0
            ),
        }
    summary = {
        "schema_version": INCOME_SCHEMA_VERSION,
        "evidence_label": INCOME_EVIDENCE_LABEL,
        "causal_claim": False,
        "scope": {
            "city": "New York City",
            "pickup_month": cfg.start_date.strftime("%Y-%m"),
            "income_source": "2022 ACS 5-year B19001 household income distribution",
            "income_reference_period": "2018-2022 five-year estimates",
            "population_claim": False,
            "individual_income_claim": False,
        },
        "definitions": {
            "income_measure": (
                "grouped median calculated from spatially allocated B19001 household "
                "income-bin counts; never a median of tract or NTA medians"
            ),
            "high_income_area": (
                "Primary-eligible Taxi Zone with dominant residential NTA and grouped "
                "median greater than or equal to the aggregate NYC grouped median"
            ),
            "low_income_area": (
                "Primary-eligible Taxi Zone with dominant residential NTA and grouped "
                "median below the aggregate NYC grouped median"
            ),
            "unclassified": (
                "no supported household distribution, including non-NYC/unknown zones "
                "and every Taxi Zone whose dominant NTA is non-residential"
            ),
            "primary_residential_eligibility": (
                "dominant NTA has pre-specified NTAType 0 (residential) and the area-"
                "allocated distribution meets the configured household minimum and "
                f"residential Taxi Zone area share >= "
                f"{cfg.minimum_residential_taxi_zone_area_share:g}"
            ),
            "all_zone_area_allocation_sensitivity": (
                "legacy classification based only on allocated households and grouped "
                "median; retained as sensitivity and never used for the primary result"
            ),
            "allocation": (
                "NTA bin counts allocated by EPSG:6933 equal-area overlap, normalized "
                "within NTA to conserve all sixteen B19001 bins"
            ),
            "grouped_median_top_coded": (
                "true means the grouped median falls in B19001's open >=$200,000 "
                "bin; the numeric value is then a $200,000 lower bound"
            ),
            "area_allocated_B19001_fields": (
                "fractional ecological allocations of official NTA counts, not exact "
                "Taxi Zone household counts"
            ),
        },
        "coverage": {
            "panel_zone_rows": int(joined["panel_zone_id"].nunique()),
            "official_taxi_zones_in_panel": int(
                joined.loc[joined["official_taxi_zone"], "panel_zone_id"].nunique()
            ),
            "classified_panel_zones": int(
                joined.loc[
                    joined["income_group"] != "unclassified",
                    "panel_zone_id",
                ].nunique()
            ),
            "published_completed_trips": int(trip_total),
            "classified_published_completed_trips": classified_trips,
            "classified_trip_coverage": classified_trips / trip_total,
            "unclassified_published_completed_trips": int(trip_total) - classified_trips,
            "observed_days": len(observed_dates),
            "dominant_nonresidential_panel_zones": int(
                joined.loc[dominant_nonresidential, "panel_zone_id"].nunique()
            ),
            "dominant_nonresidential_published_completed_trips": int(
                joined.loc[
                    dominant_nonresidential,
                    "published_completed_trips",
                ].sum()
            ),
        },
        "associations": {
            "mean_published_completed_trips_per_zone_hour_high_income_area": high_rate,
            "mean_published_completed_trips_per_zone_hour_low_income_area": low_rate,
            "high_minus_low_mean_published_completed_trips_per_zone_hour": high_rate - low_rate,
            "high_to_low_mean_published_completed_trips_per_zone_hour_ratio": (
                high_rate / low_rate if low_rate else None
            ),
        },
        "primary_classification": {
            "primary_result": True,
            "residential_nta_type_codes": list(cfg.residential_nta_type_codes),
            "minimum_allocated_households": cfg.minimum_allocated_households,
            "minimum_residential_taxi_zone_area_share": (
                cfg.minimum_residential_taxi_zone_area_share
            ),
            "groups": primary_groups,
        },
        "sensitivity": {
            "all_zone_area_allocation": {
                "primary_result": False,
                "classification_rule": (
                    "allocated households >= configured minimum; dominant NTA "
                    "residential eligibility intentionally ignored"
                ),
                "minimum_allocated_households": cfg.minimum_allocated_households,
                "ignored_primary_residential_taxi_zone_area_share_threshold": (
                    cfg.minimum_residential_taxi_zone_area_share
                ),
                "groups": sensitivity_groups,
                "classified_panel_zones": int(
                    joined.loc[sensitivity_classified, "panel_zone_id"].nunique()
                ),
                "classified_published_completed_trips": sensitivity_classified_trips,
                "classified_trip_coverage": sensitivity_classified_trips / trip_total,
                "mean_published_completed_trips_per_zone_hour_high_income_area": (
                    sensitivity_high_rate
                ),
                "mean_published_completed_trips_per_zone_hour_low_income_area": (
                    sensitivity_low_rate
                ),
                "high_minus_low_mean_published_completed_trips_per_zone_hour": (
                    sensitivity_high_rate - sensitivity_low_rate
                ),
                "high_to_low_mean_published_completed_trips_per_zone_hour_ratio": (
                    sensitivity_high_rate / sensitivity_low_rate
                    if sensitivity_low_rate
                    else None
                ),
                "dominant_nonresidential_zones_classified": int(
                    joined.loc[
                        sensitivity_nonresidential_classified,
                        "panel_zone_id",
                    ].nunique()
                ),
                "dominant_nonresidential_classified_published_completed_trips": int(
                    joined.loc[
                        sensitivity_nonresidential_classified,
                        "published_completed_trips",
                    ].sum()
                ),
            }
        },
        "classification_uncertainty": {
            "zone_grouped_medians_are_point_estimates": True,
            "zone_level_margin_of_error_propagated": False,
            "nta_b19001_margins_of_error_retained": True,
            "interpretation": (
                "Threshold proximity shows decisions most exposed to grouped-median "
                "measurement error; it is not a confidence interval"
            ),
            "threshold_proximity": threshold_proximity,
        },
        "conservation": {
            "zone_trip_sum": int(zone_summary["published_completed_trips"].sum()),
            "daily_group_trip_sum": int(daily["published_completed_trips"].sum()),
            "monthly_group_trip_sum": int(monthly["published_completed_trips"].sum()),
            "sensitivity_group_trip_sum": int(
                sensitivity_monthly["published_completed_trips"].sum()
            ),
            "primary_classified_plus_unclassified_trip_sum": int(
                joined["published_completed_trips"].sum()
            ),
            "primary_nonresidential_classified_zones": int(
                joined.loc[
                    primary_classified & dominant_nonresidential,
                    "panel_zone_id",
                ].nunique()
            ),
            "passes": (
                int(zone_summary["published_completed_trips"].sum())
                == int(daily["published_completed_trips"].sum())
                == int(monthly["published_completed_trips"].sum())
                == int(sensitivity_monthly["published_completed_trips"].sum())
                and not (primary_classified & dominant_nonresidential).any()
            ),
        },
        "limitations": [
            "ACS B19001 measures household income by residence; it is not rider or driver individual income.",
            "Area allocation assumes households are uniformly distributed within each NTA and introduces ecological measurement error.",
            "ACS margins of error are retained at NTA level, but no exact margin of error is available for area-allocated Taxi Zone grouped medians.",
            "Taxi Zone income groups use point estimates; threshold-proximity counts are diagnostics, not propagated margins of error or confidence intervals.",
            "Published completed trips omit latent requests, unserved demand, and available drivers.",
            "High-versus-low contrasts are observational descriptions confounded by land use, transit access, population, employment, time patterns, and other shocks.",
            "The primary contrast excludes Taxi Zones dominated by airports, parks, cemeteries, facilities, Rikers Island, or other non-residential NTA types; the previous all-zone rule is sensitivity only.",
            "Neither income effects, discrimination, causal demand response, nor individual behavior is identified.",
        ],
    }
    if not summary["conservation"]["passes"]:
        raise ValueError("income group tables do not conserve published trips")
    return zone_summary, daily, monthly, summary


def _verified_panel_inputs(
    panel_directory: Path,
    data_manifest_path: Path,
    project_root: Path,
) -> tuple[tuple[Path, ...], dict[str, Any], int]:
    source_manifest = json.loads(data_manifest_path.read_text(encoding="utf-8"))
    if (
        source_manifest.get("config", {}).get("source") != "nyc_hvfhv"
        or source_manifest.get("config", {}).get("mode") != "full"
        or source_manifest.get("metadata", {}).get("evidence_label")
        != "descriptive_real_data"
        or source_manifest.get("metadata", {}).get("causal_claim") is not False
    ):
        raise ValueError("income analysis requires the verified NYC full-data manifest")
    panel_paths = tuple(sorted(panel_directory.rglob("*.parquet")))
    if not panel_paths:
        raise FileNotFoundError("NYC full zone-time panel is unavailable")
    declared: dict[Path, dict[str, Any]] = {}
    for entry in source_manifest.get("files", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("NYC data manifest contains an invalid file entry")
        declared_path = Path(entry["path"])
        if declared_path.is_absolute():
            raise ValueError("NYC data manifest file paths must be project-relative")
        if ".." in declared_path.parts:
            raise ValueError("NYC data manifest file paths must not contain '..'")
        resolved = (project_root / declared_path).resolve()
        if not resolved.is_relative_to(project_root):
            raise ValueError("NYC data manifest file path resolves outside project_root")
        if resolved in declared:
            raise ValueError("NYC data manifest declares a duplicate file path")
        declared[resolved] = entry
    declared_panel = {path for path in declared if path.is_relative_to(panel_directory)}
    if set(panel_paths) != declared_panel:
        raise ValueError("NYC income panel file set differs from the source manifest")
    for path in panel_paths:
        entry = declared[path]
        if path.stat().st_size != entry.get("bytes") or sha256_file(path) != entry.get("sha256"):
            raise ValueError(f"NYC income panel lineage mismatch: {path}")
    expected_trips = int(
        source_manifest["metadata"]["full_month_processing"]["row_conservation"][
            "zone_time_trip_sum"
        ]
    )
    return panel_paths, source_manifest, expected_trips


def _manifest_entry(
    path: Path,
    root: Path,
    role: str,
    **metadata: Any,
) -> dict[str, Any]:
    return {
        "role": role,
        "path": _portable(path, root),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        **metadata,
    }


def _entry_set_digest(entries: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(list(entries), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_nyc_income_bundle(
    taxi_zone_zip_path: str | Path,
    nta_geojson_path: str | Path,
    tract_to_nta_path: str | Path,
    acs_b19001_path: str | Path,
    panel_directory: str | Path,
    data_manifest_path: str | Path,
    output_directory: str | Path,
    *,
    project_root: str | Path,
    config: NYCIncomeConfig | None = None,
) -> NYCIncomeArtifacts:
    """Publish an atomic, fail-closed, hash-manifested NYC income bundle."""

    cfg = config or NYCIncomeConfig()
    root = Path(project_root).resolve()
    taxi_path = Path(taxi_zone_zip_path).resolve()
    nta_path = Path(nta_geojson_path).resolve()
    tract_path = Path(tract_to_nta_path).resolve()
    acs_path = Path(acs_b19001_path).resolve()
    panel_root = Path(panel_directory).resolve()
    source_manifest_path = Path(data_manifest_path).resolve()
    output = Path(output_directory).resolve()
    for path in (taxi_path, nta_path, tract_path, acs_path, panel_root, source_manifest_path, output):
        _portable(path, root)
    output.mkdir(parents=True, exist_ok=True)
    marker = output / "NYC_INCOME_INCOMPLETE.json"
    manifest_path = output / "manifest.json"
    manifest_path.unlink(missing_ok=True)
    _atomic_json(
        {
            "status": "incomplete",
            "evidence_label": INCOME_EVIDENCE_LABEL,
            "causal_claim": False,
            "interpretation": "No NYC income artifact is valid while this marker exists.",
        },
        marker,
    )

    _require_pinned_file(taxi_path, cfg.expected_taxi_sha256, "TLC Taxi Zone source")
    _require_pinned_file(nta_path, cfg.expected_nta_sha256, "NYC NTA source")
    _require_pinned_file(tract_path, cfg.expected_tract_to_nta_sha256, "NYC tract-to-NTA source")
    _require_pinned_file(acs_path, cfg.expected_acs_sha256, "Census ACS B19001 source")
    if not source_manifest_path.is_file():
        raise FileNotFoundError(source_manifest_path)
    panel_paths, _source_manifest, expected_trips = _verified_panel_inputs(
        panel_root,
        source_manifest_path,
        root,
    )

    crosswalk, geometry_checks = build_taxi_zone_nta_crosswalk(taxi_path, nta_path, cfg)
    nta_codes = [
        str(feature["properties"]["nta2020"])
        for feature in json.loads(nta_path.read_text(encoding="utf-8"))["features"]
    ]
    nta_income, acs_checks = aggregate_acs_b19001_to_nta(
        tract_path,
        acs_path,
        nta_codes,
        cfg,
    )
    zone_income, allocation_checks = allocate_nta_income_to_taxi_zones(
        crosswalk,
        nta_income,
        float(acs_checks["citywide_grouped_median_household_income_usd"]),
        cfg,
    )
    zone_summary, daily, monthly, summary = income_trip_descriptions(
        panel_paths,
        zone_income,
        cfg,
    )
    if summary["conservation"]["zone_trip_sum"] != expected_trips:
        raise ValueError("NYC income descriptions do not conserve source-manifest trips")
    summary["spatial_mapping"] = geometry_checks
    summary["acs_aggregation"] = acs_checks
    summary["zone_allocation"] = allocation_checks
    summary["provenance"] = {
        "tlc_taxi_zone_url": TAXI_ZONES_URL,
        "tlc_taxi_zone_path": _portable(taxi_path, root),
        "tlc_taxi_zone_sha256": sha256_file(taxi_path),
        "nyc_nta2020_url": NTA2020_URL,
        "nyc_nta2020_path": _portable(nta_path, root),
        "nyc_nta2020_sha256": sha256_file(nta_path),
        "nyc_tract_to_nta_url": TRACT_TO_NTA_URL,
        "nyc_tract_to_nta_path": _portable(tract_path, root),
        "nyc_tract_to_nta_sha256": sha256_file(tract_path),
        "acs_b19001_parent_url": ACS_B19001_PARENT_URL,
        "acs_b19001_parent_bytes": ACS_B19001_PARENT_BYTES,
        "acs_b19001_parent_sha256": ACS_B19001_PARENT_SHA256,
        "acs_nyc_slice_path": _portable(acs_path, root),
        "acs_nyc_slice_sha256": sha256_file(acs_path),
        "acs_nyc_slice_derivation": (
            "header plus GEO_ID rows matching NYC state/county tract prefixes "
            "36005, 36047, 36061, 36081, or 36085; bytes otherwise unchanged"
        ),
        "nyc_data_manifest_path": _portable(source_manifest_path, root),
        "nyc_data_manifest_sha256": sha256_file(source_manifest_path),
        "panel_files_verified": len(panel_paths),
        "hashes_recomputed": True,
    }
    zone_summary = zone_summary.rename(
        columns={column: f"area_allocated_{column}" for column in ESTIMATE_COLUMNS}
    )

    with tempfile.TemporaryDirectory(prefix=".nyc-income-", dir=output.parent) as temporary_dir:
        stage = Path(temporary_dir)
        staged_crosswalk = _atomic_csv(crosswalk, stage / "taxi_zone_nta_crosswalk.csv")
        staged_nta = _atomic_csv(nta_income, stage / "nta_income_summary.csv")
        staged_zone = _atomic_csv(zone_summary, stage / "zone_income_summary.csv")
        staged_daily = _atomic_csv(daily, stage / "income_group_daily.csv")
        staged_monthly = _atomic_csv(monthly, stage / "income_group_monthly.csv")
        staged_summary = _atomic_json(summary, stage / "income_associations.json")
        output_specs = (
            (staged_crosswalk, output / staged_crosswalk.name, "taxi_zone_nta_crosswalk"),
            (staged_nta, output / staged_nta.name, "nta_b19001_distribution_summary"),
            (staged_zone, output / staged_zone.name, "taxi_zone_income_and_trip_summary"),
            (staged_daily, output / staged_daily.name, "daily_income_group_description"),
            (staged_monthly, output / staged_monthly.name, "monthly_income_group_description"),
            (staged_summary, output / staged_summary.name, "income_association_summary"),
        )
        file_entries = [
            {
                "role": role,
                "path": _portable(destination, root),
                "bytes": staged.stat().st_size,
                "sha256": sha256_file(staged),
                "evidence_label": INCOME_EVIDENCE_LABEL,
                "causal_claim": False,
            }
            for staged, destination, role in output_specs
        ]
        input_entries = [
            _manifest_entry(
                taxi_path,
                root,
                "official_tlc_taxi_zone_geometry",
                source_url=TAXI_ZONES_URL,
                source_type="official_observed_geometry",
            ),
            _manifest_entry(
                nta_path,
                root,
                "official_nyc_nta2020_geometry",
                source_url=NTA2020_URL,
                source_type="official_observed_geometry",
            ),
            _manifest_entry(
                tract_path,
                root,
                "official_nyc_tract2020_to_nta2020_mapping",
                source_url=TRACT_TO_NTA_URL,
                source_type="official_observed_crosswalk",
            ),
            _manifest_entry(
                acs_path,
                root,
                "official_census_acs_2022_5yr_b19001_nyc_tract_slice",
                source_url=ACS_B19001_PARENT_URL,
                source_type="official_observed_estimates",
                parent_bytes=ACS_B19001_PARENT_BYTES,
                parent_sha256=ACS_B19001_PARENT_SHA256,
            ),
            _manifest_entry(
                source_manifest_path,
                root,
                "verified_nyc_full_data_manifest",
                source_type="descriptive_real_data_lineage",
            ),
        ]
        input_entries.extend(
            _manifest_entry(
                panel_path,
                root,
                "nyc_full_zone_time_panel",
                source_type="descriptive_real_data_panel",
            )
            for panel_path in panel_paths
        )
        staged_manifest = _atomic_json(
            {
                "schema_version": INCOME_SCHEMA_VERSION,
                "artifact_type": "nyc_income_descriptive_bundle",
                "evidence_label": INCOME_EVIDENCE_LABEL,
                "causal_claim": False,
                "portable_paths": True,
                "files": file_entries,
                "inputs": input_entries,
                "declared_file_set_sha256": _entry_set_digest(file_entries),
                "declared_input_set_sha256": _entry_set_digest(input_entries),
                "checks": {
                    "official_source_hashes_match": True,
                    "taxi_location_ids_unique_and_complete": True,
                    "tract_b19001_totals_equal_sixteen_bins": True,
                    "median_of_medians_used": False,
                    "equal_area_crs": cfg.equal_area_crs,
                    "household_distribution_conserved": True,
                    "published_trip_conservation": True,
                    "panel_files_verified": len(panel_paths),
                    "classified_trip_coverage": summary["coverage"]["classified_trip_coverage"],
                    "residential_nta_type_codes": list(
                        cfg.residential_nta_type_codes
                    ),
                    "minimum_allocated_households": cfg.minimum_allocated_households,
                    "minimum_residential_taxi_zone_area_share": (
                        cfg.minimum_residential_taxi_zone_area_share
                    ),
                    "dominant_nonresidential_primary_classified_zones": summary[
                        "conservation"
                    ]["primary_nonresidential_classified_zones"],
                    "dominant_nonresidential_primary_unclassified": (
                        summary["conservation"][
                            "primary_nonresidential_classified_zones"
                        ]
                        == 0
                    ),
                    "all_zone_classification_is_sensitivity_only": True,
                    "zone_grouped_medians_are_point_estimates": True,
                    "zone_level_margin_of_error_propagated": False,
                    "ecological_noncausal_contract": True,
                },
            },
            stage / "manifest.json",
        )
        for staged, destination, _role in output_specs:
            staged.replace(destination)
        staged_manifest.replace(manifest_path)

    if not manifest_path.is_file():
        raise RuntimeError("NYC income bundle completed without a manifest")
    marker.unlink(missing_ok=True)
    return NYCIncomeArtifacts(
        crosswalk_path=output / "taxi_zone_nta_crosswalk.csv",
        nta_income_path=output / "nta_income_summary.csv",
        zone_income_path=output / "zone_income_summary.csv",
        daily_path=output / "income_group_daily.csv",
        monthly_path=output / "income_group_monthly.csv",
        summary_path=output / "income_associations.json",
        manifest_path=manifest_path,
    )


__all__ = [
    "ACS_B19001_NYC_SLICE_SHA256",
    "ACS_B19001_PARENT_SHA256",
    "ACS_B19001_PARENT_URL",
    "INCOME_EVIDENCE_LABEL",
    "NYCIncomeArtifacts",
    "NYCIncomeConfig",
    "NTA2020_SHA256",
    "NTA2020_URL",
    "TAXI_ZONES_SHA256",
    "TAXI_ZONES_URL",
    "TRACT_TO_NTA_SHA256",
    "TRACT_TO_NTA_URL",
    "aggregate_acs_b19001_to_nta",
    "allocate_nta_income_to_taxi_zones",
    "build_taxi_zone_nta_crosswalk",
    "income_trip_descriptions",
    "write_nyc_income_bundle",
]
