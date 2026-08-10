from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from macro_nowcast.adapters import (
    AdapterAuthorizationError,
    AdapterCredentialError,
    AdapterRequestError,
    FixtureAdapter,
    FredAlfredAdapter,
    RetryableAdapterError,
    parse_fred_observations,
)
from macro_nowcast.config import FredAPIConfig, SeriesConfig, load_data_config
from macro_nowcast.schema import observations_to_frame

DOWNLOADED_AT = datetime(2026, 8, 7, 15, 0, tzinfo=UTC)


def _series() -> SeriesConfig:
    return SeriesConfig(
        series_id="PAYEMS",
        units="thousands_of_persons",
        frequency="monthly",
        seasonal_adjustment="seasonally_adjusted",
        transformation="level",
    )


def _fred_payload() -> dict[str, object]:
    return {
        "realtime_start": "2020-02-07",
        "realtime_end": "2020-03-05",
        "count": 2,
        "observations": [
            {
                "realtime_start": "2020-02-07",
                "realtime_end": "2020-03-05",
                "date": "2020-01-01",
                "value": "152100.0",
            },
            {
                "realtime_start": "2020-03-06",
                "realtime_end": "9999-12-31",
                "date": "2020-01-01",
                "value": ".",
            },
        ],
    }


def test_parse_alfred_shape_preserves_vintage_and_provenance() -> None:
    rows = parse_fred_observations(
        _fred_payload(),
        series=_series(),
        source="alfred",
        provenance_label="alfred_api",
        download_timestamp=DOWNLOADED_AT,
    )

    assert [row.realtime_start for row in rows] == [date(2020, 2, 7), date(2020, 3, 6)]
    assert [row.availability_date for row in rows] == [
        date(2020, 2, 7),
        date(2020, 3, 6),
    ]
    assert rows[1].value is None
    assert rows[0].source_metadata["availability_basis"] == "alfred_realtime_start"
    assert rows[0].provenance_label == "alfred_api"
    assert rows[0].download_timestamp == DOWNLOADED_AT


def test_fixture_adapter_is_offline_and_forces_fixture_label(tmp_path: Path) -> None:
    source_row = parse_fred_observations(
        _fred_payload(),
        series=_series(),
        source="alfred",
        provenance_label="should_not_survive",
        download_timestamp=DOWNLOADED_AT,
    )[0]
    fixture_path = tmp_path / "observations.json"
    fixture_path.write_text(json.dumps([source_row.to_storage_dict()], default=str))

    from_file = FixtureAdapter(fixture_path).fetch("PAYEMS")
    from_frame = FixtureAdapter(observations_to_frame([source_row])).fetch(_series())

    assert from_file[0].provenance_label == "synthetic_fixture"
    assert from_file[0].source_metadata["fixture_name"] == "observations.json"
    assert from_frame[0].provenance_label == "synthetic_fixture"
    assert from_frame[0].source_metadata["fixture_name"] == "in_memory_frame"


def test_live_adapter_fails_closed_without_network_access() -> None:
    calls: list[str] = []

    def forbidden_transport(url: str, timeout: float) -> bytes:
        calls.append(url)
        raise AssertionError(f"unexpected network transport with timeout {timeout}")

    adapter = FredAlfredAdapter(transport=forbidden_transport, environ={"FRED_API_KEY": "key"})
    with pytest.raises(AdapterAuthorizationError):
        adapter.fetch(_series())

    authorized = FredAlfredAdapter(
        FredAPIConfig(terms_authorized=True),
        transport=forbidden_transport,
        environ={},
    )
    with pytest.raises(AdapterCredentialError, match="FRED_API_KEY"):
        authorized.fetch(_series())
    assert calls == []


def test_live_adapter_uses_injected_transport_and_configured_retry() -> None:
    calls = 0
    sleeps: list[float] = []

    def fixture_transport(url: str, timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        assert "api_key=fixture-key" in url
        assert timeout == 4.0
        if calls == 1:
            raise RetryableAdapterError("transient fixture failure")
        return json.dumps(_fred_payload()).encode()

    adapter = FredAlfredAdapter(
        FredAPIConfig(
            terms_authorized=True,
            timeout_seconds=4,
            min_interval_seconds=0,
            max_attempts=2,
            initial_backoff_seconds=0.25,
        ),
        environ={"FRED_API_KEY": "fixture-key"},
        transport=fixture_transport,
        sleep=sleeps.append,
        now=lambda: DOWNLOADED_AT,
    )
    rows = adapter.fetch(_series())

    assert calls == 2
    assert sleeps == [0.25]
    assert rows[0].provenance_label == "fred_alfred_api"
    assert "api_key" not in rows[0].source_metadata["request_parameters"]


def test_live_adapter_uses_interval_history_defaults_and_paginates() -> None:
    urls: list[str] = []

    def paginated_transport(url: str, timeout: float) -> bytes:
        del timeout
        urls.append(url)
        query = parse_qs(urlparse(url).query)
        offset = int(query["offset"][0])
        observations = [
            {
                "realtime_start": "2020-02-07",
                "realtime_end": "9999-12-31",
                "date": f"2020-0{offset + 1}-01",
                "value": str(100 + offset),
            }
        ]
        return json.dumps({"count": 2, "observations": observations}).encode()

    adapter = FredAlfredAdapter(
        FredAPIConfig(terms_authorized=True, min_interval_seconds=0),
        environ={"FRED_API_KEY": "fixture-key"},
        transport=paginated_transport,
        now=lambda: DOWNLOADED_AT,
    )

    rows = adapter.fetch(_series())

    assert len(rows) == 2
    queries = [parse_qs(urlparse(url).query) for url in urls]
    assert [query["offset"][0] for query in queries] == ["0", "1"]
    assert all(query["output_type"] == ["1"] for query in queries)
    assert all(query["realtime_start"] == ["1776-07-04"] for query in queries)
    assert all(query["realtime_end"] == ["9999-12-31"] for query in queries)
    assert all(query["limit"] == ["100000"] for query in queries)


def test_live_adapter_rejects_cross_tab_output_without_transport() -> None:
    adapter = FredAlfredAdapter(transport=lambda *_: b"{}")

    with pytest.raises(AdapterRequestError, match="output_type"):
        adapter.fetch(_series(), output_type=2)


def test_series_catalog_loads_with_live_access_disabled_by_default() -> None:
    root = Path(__file__).parents[1]
    config = load_data_config(root / "config" / "series.toml")

    assert config.require_series("PAYEMS").role.value == "target"
    assert len(config.series) == 10
    assert config.fred.api_key_env == "FRED_API_KEY"
    assert config.fred.terms_authorized is False
    assert config.fred.cache_dir is None
