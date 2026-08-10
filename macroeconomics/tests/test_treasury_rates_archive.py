from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from macro_nowcast.treasury_rates_archive import (
    TREASURY_10Y_SERIES_ID,
    TREASURY_RATES_TIMING_QUALITY,
    TreasuryRatesArchiveError,
    audit_treasury_rates_archive,
    parse_treasury_rate_feed,
    parse_treasury_rates_archive,
)


def _feed(year: int, rows: list[tuple[str, str | None]]) -> bytes:
    entries = []
    for observation_date, value in rows:
        value_node = (
            "" if value is None else f'<d:BC_10YEAR m:type="Edm.Double">{value}</d:BC_10YEAR>'
        )
        entries.append(
            "<entry><content type=\"application/xml\"><m:properties>"
            f'<d:NEW_DATE m:type="Edm.DateTime">{observation_date}T00:00:00</d:NEW_DATE>'
            f"{value_node}</m:properties></content></entry>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" '
        'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
        "<title>DailyTreasuryYieldCurveRateData</title>"
        f"<updated>{year + 1}-01-03T18:30:00Z</updated>"
        f"{''.join(entries)}</feed>"
    ).encode()


def _write_year(
    root: Path,
    year: int,
    rows: list[tuple[str, str | None]],
) -> dict[str, object]:
    payload = _feed(year, rows)
    path = root / "years" / f"{year}.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    timestamp = datetime(2026, 8, 10, 12, tzinfo=UTC).timestamp()
    path.touch()
    path.chmod(0o600)
    return {
        "year": year,
        "url": (
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
            "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value="
            f"{year}"
        ),
        "content_type": "text/xml",
        "path": f"years/{year}.xml",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "feed_updated": f"{year + 1}-01-03T18:30:00+00:00",
        "observation_count": sum(value is not None for _, value in rows),
        "first_observation_date": rows[0][0],
        "last_observation_date": rows[-1][0],
        "fixture_timestamp": timestamp,
    }


def test_feed_parser_retains_10_year_values_and_skips_explicit_missing() -> None:
    parsed = parse_treasury_rate_feed(
        _feed(
            2024,
            [
                ("2024-01-02", "3.95"),
                ("2024-01-03", None),
                ("2024-01-04", "3.99"),
            ],
        ),
        requested_year=2024,
    )

    assert parsed.feed_updated == datetime(2025, 1, 3, 18, 30, tzinfo=UTC)
    assert parsed.observations == (
        (date(2024, 1, 2), 3.95),
        (date(2024, 1, 4), 3.99),
    )


def test_feed_parser_fails_closed_on_wrong_year_and_duplicate_date() -> None:
    with pytest.raises(TreasuryRatesArchiveError, match="contains"):
        parse_treasury_rate_feed(
            _feed(2024, [("2023-12-29", "3.88")]),
            requested_year=2024,
        )
    with pytest.raises(TreasuryRatesArchiveError, match="duplicate"):
        parse_treasury_rate_feed(
            _feed(2024, [("2024-01-02", "3.95"), ("2024-01-02", "3.96")]),
            requested_year=2024,
        )


def test_local_archive_audit_and_parser_use_conservative_eod_availability(
    tmp_path: Path,
) -> None:
    root = tmp_path / "treasury-yield-curve"
    years = [
        _write_year(root, 2023, [("2023-12-28", "3.84"), ("2023-12-29", "3.88")]),
        _write_year(root, 2024, [("2024-01-02", "3.95"), ("2024-01-03", "3.91")]),
    ]
    (root / "release-index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "US_TREASURY_DAILY_PAR_YIELD_CURVE",
                "years": years,
            }
        ),
        encoding="utf-8",
    )

    observations = parse_treasury_rates_archive(root)
    audit = audit_treasury_rates_archive(root)

    assert len(observations) == 4
    assert {row.series_id for row in observations} == {TREASURY_10Y_SERIES_ID}
    assert observations[0].release_timestamp is None
    assert observations[0].availability_timestamp == datetime(
        2023,
        12,
        29,
        4,
        59,
        59,
        999999,
        tzinfo=UTC,
    )
    assert observations[0].source_metadata["publication_vintage_dimension_available"] is False
    assert observations[0].source_metadata["timing_quality"] == TREASURY_RATES_TIMING_QUALITY
    assert audit["passed"] is True
    assert audit["canonical_observation_rows"] == 4
    assert audit["publication_vintage_dimension_available"] is False
    assert audit["exact_publication_clock_claimed"] is False


def test_archive_rejects_hash_and_inventory_drift(tmp_path: Path) -> None:
    root = tmp_path / "treasury-yield-curve"
    entry = _write_year(root, 2024, [("2024-01-02", "3.95")])
    (root / "release-index.json").write_text(
        json.dumps({"schema_version": 1, "years": [entry]}),
        encoding="utf-8",
    )
    (root / "years" / "2024.xml").write_bytes(b"changed")

    with pytest.raises(TreasuryRatesArchiveError, match="hash mismatch"):
        audit_treasury_rates_archive(root)
