from __future__ import annotations

import json
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from macro_nowcast.agency_adapters import (
    ARCHIVE_MANIFESTS,
    BEA_API_KEY_ENV,
    BEA_GDP_ARCHIVE,
    BEA_REAL_GDP_GROWTH,
    BEA_REAL_GDP_LEVEL,
    BLS_CES_VINTAGE_ARCHIVE,
    BLS_CORE_CPI,
    BLS_CPI_SUPPLEMENTAL_ARCHIVE,
    BLS_REGISTRATION_KEY_ENV,
    BLS_TOTAL_NONFARM_PAYROLL,
    LATEST_REVISED,
    UMICH_SENTIMENT_PUBLIC_REPORTS,
    AgencyAuthorizationError,
    AgencyCredentialError,
    AgencyProvenanceError,
    AgencyRequestError,
    AgencyRequestPolicy,
    ArchiveIngestionApproval,
    BEALatestAdapter,
    BEALatestConfig,
    BLSLatestAdapter,
    BLSLatestConfig,
    HTTPRequest,
    HTTPResponse,
    UMichSentimentIngestionApproval,
    build_bea_latest_request,
    build_bls_latest_request,
    parse_bea_latest_response,
    parse_bls_latest_response,
    require_archive_ingestion_approval,
    require_umich_sentiment_ingestion_approval,
)

RETRIEVED_AT = datetime(2026, 8, 7, 14, 30, tzinfo=UTC)


def _no_wait_policy(*, max_attempts: int = 1) -> AgencyRequestPolicy:
    return AgencyRequestPolicy(
        min_interval_seconds=0,
        max_attempts=max_attempts,
        initial_backoff_seconds=0,
    )


def _bls_payload() -> dict[str, object]:
    return {
        "status": "REQUEST_SUCCEEDED",
        "message": [],
        "Results": {
            "series": [
                {
                    "seriesID": BLS_TOTAL_NONFARM_PAYROLL.series_id,
                    "data": [
                        {
                            "year": "2026",
                            "period": "M06",
                            "periodName": "June",
                            "latest": "true",
                            "value": "159,540",
                            "footnotes": [{"code": "P", "text": "Preliminary"}],
                        },
                        {
                            "year": "2026",
                            "period": "M13",
                            "periodName": "Annual",
                            "value": "159000",
                        },
                    ],
                }
            ]
        },
    }


def _bea_payload() -> dict[str, object]:
    return {
        "BEAAPI": {
            "Results": {
                "Data": [
                    {
                        "TableName": "T10101",
                        "SeriesCode": "A191RL",
                        "LineNumber": "1",
                        "LineDescription": "Gross domestic product",
                        "TimePeriod": "2026Q2",
                        "Metric_Name": "Percent Change from Preceding Period",
                        "CL_UNIT": "Percent change, annual rate",
                        "UNIT_MULT": "0",
                        "DataValue": "3.0",
                    },
                    {
                        "TableName": "T10101",
                        "SeriesCode": "A006RL",
                        "LineNumber": "2",
                        "LineDescription": "Personal consumption expenditures",
                        "TimePeriod": "2026Q2",
                        "DataValue": "1.2",
                    },
                ]
            }
        }
    }


def test_bls_fails_closed_before_credential_lookup_or_transport() -> None:
    calls: list[HTTPRequest] = []

    def forbidden(request: HTTPRequest, timeout_seconds: float) -> HTTPResponse:
        del timeout_seconds
        calls.append(request)
        raise AssertionError("transport must remain offline")

    adapter = BLSLatestAdapter(
        transport=forbidden,
        environ={BLS_REGISTRATION_KEY_ENV: "fixture-secret"},
    )

    with pytest.raises(AgencyAuthorizationError, match="terms_authorized=True"):
        adapter.fetch(BLS_TOTAL_NONFARM_PAYROLL, start_year=2025, end_year=2026)

    assert calls == []


def test_agency_clients_use_only_their_exact_environment_variables() -> None:
    unrelated_secret = "must-not-be-used"
    bls = BLSLatestAdapter(
        BLSLatestConfig(terms_authorized=True),
        transport=lambda *_: pytest.fail("unexpected transport"),
        environ={"FRED_API_KEY": unrelated_secret},
    )
    bea = BEALatestAdapter(
        BEALatestConfig(terms_authorized=True),
        transport=lambda *_: pytest.fail("unexpected transport"),
        environ={BLS_REGISTRATION_KEY_ENV: unrelated_secret},
    )

    with pytest.raises(AgencyCredentialError, match=BLS_REGISTRATION_KEY_ENV) as bls_error:
        bls.fetch(BLS_CORE_CPI, start_year=2026, end_year=2026)
    with pytest.raises(AgencyCredentialError, match=BEA_API_KEY_ENV) as bea_error:
        bea.fetch(BEA_REAL_GDP_GROWTH, years=[2026])

    assert unrelated_secret not in str(bls_error.value)
    assert unrelated_secret not in str(bea_error.value)
    assert unrelated_secret not in repr(bls)
    assert unrelated_secret not in repr(bea)


def test_bls_request_builder_redacts_registration_key_from_repr() -> None:
    secret = "bls-key/with+characters"
    request = build_bls_latest_request(
        [BLS_TOTAL_NONFARM_PAYROLL.series_id],
        start_year=2025,
        end_year=2026,
        registration_key=secret,
    )

    assert request.method == "POST"
    assert json.loads(request.body or b"{}")["registrationkey"] == secret
    assert secret not in repr(request)
    assert secret not in request.redacted_url


def test_bea_request_builder_redacts_api_key_from_repr() -> None:
    secret = "bea-key/with+characters"
    request = build_bea_latest_request(
        api_key=secret,
        table_name="T10101",
        years=[2025, 2026],
    )
    query = parse_qs(urlparse(request.url).query)

    assert request.method == "GET"
    assert query["UserID"] == [secret]
    assert query["datasetname"] == ["NIPA"]
    assert query["Year"] == ["2025,2026"]
    assert secret not in repr(request)
    assert secret not in request.redacted_url


def test_bea_real_gdp_level_is_distinct_from_already_transformed_growth() -> None:
    assert BEA_REAL_GDP_LEVEL.table_name == "T10106"
    assert BEA_REAL_GDP_LEVEL.line_number == "1"
    assert BEA_REAL_GDP_LEVEL.series_id == "GDPC1"
    assert BEA_REAL_GDP_LEVEL.transformation == "level"
    assert BEA_REAL_GDP_GROWTH.table_name == "T10101"
    assert BEA_REAL_GDP_GROWTH.transformation == "percent_change_qoq_saar"


def test_bls_adapter_parses_current_data_only_as_latest_revised() -> None:
    requests: list[HTTPRequest] = []

    def fixture_transport(request: HTTPRequest, timeout_seconds: float) -> HTTPResponse:
        requests.append(request)
        assert timeout_seconds == 30
        assert json.loads(request.body or b"{}")["registrationkey"] == "bls-fixture-key"
        return HTTPResponse(200, json.dumps(_bls_payload()), {})

    adapter = BLSLatestAdapter(
        BLSLatestConfig(terms_authorized=True, request_policy=_no_wait_policy()),
        transport=fixture_transport,
        environ={BLS_REGISTRATION_KEY_ENV: "bls-fixture-key"},
        now=lambda: RETRIEVED_AT,
    )
    rows = adapter.fetch(BLS_TOTAL_NONFARM_PAYROLL, start_year=2026, end_year=2026)

    assert len(requests) == 1
    assert len(rows) == 1  # M13 annual average is not a monthly observation.
    assert rows[0].observation_date == date(2026, 6, 1)
    assert rows[0].value == 159_540.0
    assert rows[0].provenance_label == LATEST_REVISED
    assert rows[0].realtime_start == RETRIEVED_AT.date()
    assert rows[0].availability_date == RETRIEVED_AT.date()
    assert rows[0].availability_timestamp == RETRIEVED_AT
    assert rows[0].release_timestamp is None
    assert rows[0].source_metadata["availability_basis"] == (
        "retrieval_timestamp_not_historical_release"
    )
    assert "bls-fixture-key" not in repr(requests[0])
    assert "bls-fixture-key" not in json.dumps(rows[0].source_metadata)


@pytest.mark.parametrize("label", ["first_release", "vintage_aware", "preliminary"])
def test_bls_current_api_cannot_be_labeled_as_historical_release(label: str) -> None:
    calls = 0

    def forbidden(*_: object) -> HTTPResponse:
        nonlocal calls
        calls += 1
        raise AssertionError("provenance validation must precede transport")

    adapter = BLSLatestAdapter(
        BLSLatestConfig(terms_authorized=True),
        transport=forbidden,
        environ={BLS_REGISTRATION_KEY_ENV: "secret"},
    )

    with pytest.raises(AgencyProvenanceError, match="latest_revised"):
        adapter.fetch(
            BLS_TOTAL_NONFARM_PAYROLL,
            start_year=2026,
            end_year=2026,
            provenance_label=label,
        )

    assert calls == 0


def test_bea_adapter_parses_current_nipa_row_only_as_latest_revised() -> None:
    requests: list[HTTPRequest] = []

    def fixture_transport(request: HTTPRequest, timeout_seconds: float) -> HTTPResponse:
        requests.append(request)
        assert timeout_seconds == 30
        assert parse_qs(urlparse(request.url).query)["UserID"] == ["bea-fixture-key"]
        return HTTPResponse(200, json.dumps(_bea_payload()), {})

    adapter = BEALatestAdapter(
        BEALatestConfig(terms_authorized=True, request_policy=_no_wait_policy()),
        transport=fixture_transport,
        environ={BEA_API_KEY_ENV: "bea-fixture-key"},
        now=lambda: RETRIEVED_AT,
    )
    rows = adapter.fetch(BEA_REAL_GDP_GROWTH, years=[2026])

    assert len(requests) == 1
    assert len(rows) == 1
    assert rows[0].series_id == "BEA_REAL_GDP_GROWTH_QOQ_SAAR"
    assert rows[0].observation_date == date(2026, 4, 1)
    assert rows[0].value == 3.0
    assert rows[0].provenance_label == LATEST_REVISED
    assert rows[0].availability_timestamp == RETRIEVED_AT
    assert rows[0].release_timestamp is None
    assert rows[0].source_metadata["SeriesCode"] == "A191RL"
    assert "bea-fixture-key" not in repr(requests[0])
    assert "bea-fixture-key" not in json.dumps(rows[0].source_metadata)


def test_parsers_reject_first_release_labels_directly() -> None:
    with pytest.raises(AgencyProvenanceError):
        parse_bls_latest_response(
            _bls_payload(),
            BLS_TOTAL_NONFARM_PAYROLL,
            retrieved_at=RETRIEVED_AT,
            provenance_label="first_release",
        )
    with pytest.raises(AgencyProvenanceError):
        parse_bea_latest_response(
            _bea_payload(),
            BEA_REAL_GDP_GROWTH,
            retrieved_at=RETRIEVED_AT,
            provenance_label="first_release",
        )


def test_429_retry_after_is_honored_and_bounded() -> None:
    calls = 0
    sleeps: list[float] = []

    def throttled_transport(request: HTTPRequest, timeout_seconds: float) -> HTTPResponse:
        nonlocal calls
        del request, timeout_seconds
        calls += 1
        if calls == 1:
            return HTTPResponse(429, "rate limited", {"Retry-After": "2"})
        return HTTPResponse(200, json.dumps(_bea_payload()), {})

    policy = AgencyRequestPolicy(
        min_interval_seconds=0,
        max_attempts=2,
        initial_backoff_seconds=0.25,
        max_retry_after_seconds=30,
    )
    adapter = BEALatestAdapter(
        BEALatestConfig(terms_authorized=True, request_policy=policy),
        transport=throttled_transport,
        environ={BEA_API_KEY_ENV: "fixture-key"},
        sleep=sleeps.append,
        now=lambda: RETRIEVED_AT,
    )

    assert adapter.fetch(BEA_REAL_GDP_GROWTH, years=[2026])[0].value == 3.0
    assert calls == 2
    assert sleeps == [2.0]


def test_transport_errors_and_response_repr_do_not_expose_credentials() -> None:
    secret = "highly-sensitive-fixture-key"

    def failing_transport(request: HTTPRequest, timeout_seconds: float) -> HTTPResponse:
        del timeout_seconds
        raise RuntimeError(f"failed request {request.url} using {secret}")

    adapter = BEALatestAdapter(
        BEALatestConfig(terms_authorized=True, request_policy=_no_wait_policy()),
        transport=failing_transport,
        environ={BEA_API_KEY_ENV: secret},
    )

    with pytest.raises(AgencyRequestError) as error:
        adapter.fetch(BEA_REAL_GDP_GROWTH, years=[2026])

    response = HTTPResponse(429, f"echoed {secret}", {"Retry-After": "1"})
    assert secret not in str(error.value)
    assert secret not in repr(error.value)
    assert secret not in repr(adapter)
    assert secret not in repr(response)


def test_archive_manifests_are_discovery_only_and_fail_closed() -> None:
    assert ARCHIVE_MANIFESTS == (
        BLS_CES_VINTAGE_ARCHIVE,
        BLS_CPI_SUPPLEMENTAL_ARCHIVE,
        BEA_GDP_ARCHIVE,
        UMICH_SENTIMENT_PUBLIC_REPORTS,
    )
    assert all(not manifest.default_enabled for manifest in ARCHIVE_MANIFESTS)
    assert all(not manifest.coverage_audited for manifest in ARCHIVE_MANIFESTS)

    with pytest.raises(AgencyAuthorizationError, match="terms"):
        require_archive_ingestion_approval(ArchiveIngestionApproval())
    with pytest.raises(AgencyAuthorizationError, match="opt-in"):
        require_archive_ingestion_approval(ArchiveIngestionApproval(terms_authorized=True))
    with pytest.raises(AgencyAuthorizationError, match="coverage audit"):
        require_archive_ingestion_approval(
            ArchiveIngestionApproval(terms_authorized=True, opt_in=True)
        )

    require_archive_ingestion_approval(
        ArchiveIngestionApproval(
            terms_authorized=True,
            opt_in=True,
            coverage_audited=True,
        )
    )


def test_michigan_sentiment_requires_source_specific_written_permission() -> None:
    with pytest.raises(AgencyAuthorizationError, match="usage agreement"):
        require_umich_sentiment_ingestion_approval(UMichSentimentIngestionApproval())
    with pytest.raises(AgencyAuthorizationError, match="written permission"):
        require_umich_sentiment_ingestion_approval(
            UMichSentimentIngestionApproval(terms_reviewed=True)
        )
    with pytest.raises(AgencyAuthorizationError, match="organization"):
        require_umich_sentiment_ingestion_approval(
            UMichSentimentIngestionApproval(
                terms_reviewed=True,
                written_permission_reference="permission-email-2026-08-10",
            )
        )
    with pytest.raises(AgencyAuthorizationError, match="opt-in"):
        require_umich_sentiment_ingestion_approval(
            UMichSentimentIngestionApproval(
                terms_reviewed=True,
                written_permission_reference="permission-email-2026-08-10",
                organization_scope_confirmed=True,
            )
        )
    with pytest.raises(AgencyAuthorizationError, match="coverage audit"):
        require_umich_sentiment_ingestion_approval(
            UMichSentimentIngestionApproval(
                terms_reviewed=True,
                written_permission_reference="permission-email-2026-08-10",
                organization_scope_confirmed=True,
                opt_in=True,
            )
        )

    require_umich_sentiment_ingestion_approval(
        UMichSentimentIngestionApproval(
            terms_reviewed=True,
            written_permission_reference="permission-email-2026-08-10",
            organization_scope_confirmed=True,
            opt_in=True,
            coverage_audited=True,
        )
    )
