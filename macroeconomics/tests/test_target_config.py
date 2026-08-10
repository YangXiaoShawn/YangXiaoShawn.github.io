from __future__ import annotations

import copy
import tomllib
from datetime import date
from pathlib import Path

import pytest

from macro_nowcast.target_config import (
    DEFAULT_TARGET_CONFIG_PATH,
    FEATURE_SPEC_FIELD_NAMES,
    TargetConfigError,
    load_target_config,
    parse_target_config,
)


def _document() -> dict[str, object]:
    with DEFAULT_TARGET_CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def _targets(document: dict[str, object]) -> list[dict[str, object]]:
    targets = document["targets"]
    assert isinstance(targets, list)
    return targets


def _target(document: dict[str, object], series_id: str) -> dict[str, object]:
    return next(target for target in _targets(document) if target["series_id"] == series_id)


def test_default_loader_resolves_repo_config_without_secrets() -> None:
    config = load_target_config()

    assert config.source_path == DEFAULT_TARGET_CONFIG_PATH.resolve()
    assert config.provenance_label == "synthetic_fixture"
    assert config.data_mode == "synthetic_fixture"
    assert config.is_default is True
    assert set(config.by_series) == {"PAYEMS", "CPILFESL", "GDPC1"}
    assert "api_key" not in DEFAULT_TARGET_CONFIG_PATH.read_text().lower()
    assert "secret" not in DEFAULT_TARGET_CONFIG_PATH.read_text().lower()


def test_target_definitions_have_unambiguous_formulas_and_evaluation_windows() -> None:
    config = load_target_config()
    payroll = config.get("payems")
    inflation = config.get("CPILFESL")
    gdp = config.get_by_name("real_gdp_pct_change_qoq_saar")

    assert payroll.name == "payems_change_mom_thousands"
    assert payroll.frequency == "monthly"
    assert payroll.transformation == "difference"
    assert payroll.formula == "current_level - prior_level"
    assert payroll.minimum_train_periods == 36

    assert inflation.name == "core_cpi_pct_change_mom"
    assert inflation.transformation == "percent_change"
    assert inflation.annualization == "nonannualized"
    assert inflation.formula == "100 * (current_level / prior_level - 1)"
    assert inflation.evaluation_start == date(2021, 2, 1)
    assert inflation.minimum_train_periods == 36

    assert gdp.frequency == "quarterly"
    assert gdp.transformation == "annualized_percent_change"
    assert gdp.annualization == "saar"
    assert gdp.annualization_factor == 4
    assert gdp.formula == "100 * ((current_level / prior_level) ** 4 - 1)"
    assert gdp.evaluation_start == date(2021, 1, 1)
    assert gdp.evaluation_end == date(2024, 10, 1)
    assert gdp.minimum_train_periods == 12

    assert payroll.to_target_spec().formula == payroll.formula
    assert inflation.to_target_spec().formula == inflation.formula
    assert gdp.to_target_spec().formula == gdp.formula


def test_feature_lists_use_runtime_field_names_and_are_unique_per_target() -> None:
    config = load_target_config()

    for target in config.targets:
        assert 1 <= len(target.features) <= 10
        assert len({feature.name for feature in target.features}) == len(target.features)
        assert len({feature.series_id for feature in target.features}) == len(
            target.features
        )
        for feature in target.features:
            assert tuple(feature.as_feature_spec_kwargs()) == FEATURE_SPEC_FIELD_NAMES

    payroll_feature = config.get("PAYEMS").features[0]
    assert payroll_feature.to_feature_spec().name == "payems_change_lag1"
    gdp_feature = config.get("GDPC1").features[0]
    assert gdp_feature.frequency == "quarterly"
    assert gdp_feature.transformation == "annualized_percent_change"
    assert gdp_feature.runtime_feature_spec_supported is True
    assert gdp_feature.to_feature_spec().frequency == "quarterly"


@pytest.mark.parametrize(
    ("series_id", "annualization", "message"),
    [
        ("CPILFESL", "saar", "explicitly use annualization='nonannualized'"),
        ("GDPC1", "nonannualized", "requires quarterly frequency"),
        ("PAYEMS", "saar", "annualization='not_applicable'"),
    ],
)
def test_ambiguous_annualization_fails_fast(
    series_id: str,
    annualization: str,
    message: str,
) -> None:
    document = _document()
    _target(document, series_id)["annualization"] = annualization

    with pytest.raises(TargetConfigError, match=message):
        parse_target_config(document)


def test_missing_annualization_is_rejected_as_missing_not_inferred() -> None:
    document = _document()
    del _target(document, "CPILFESL")["annualization"]

    with pytest.raises(TargetConfigError, match="missing fields: annualization"):
        parse_target_config(document)


def test_duplicate_target_names_and_series_fail_fast() -> None:
    duplicate_series = _document()
    copied = copy.deepcopy(_target(duplicate_series, "PAYEMS"))
    copied["name"] = "otherwise_unique_target_name"
    _targets(duplicate_series).append(copied)
    with pytest.raises(TargetConfigError, match="duplicate target series_id"):
        parse_target_config(duplicate_series)

    duplicate_name = _document()
    _target(duplicate_name, "CPILFESL")["name"] = _target(
        duplicate_name, "PAYEMS"
    )["name"]
    with pytest.raises(TargetConfigError, match="duplicate target name"):
        parse_target_config(duplicate_name)


def test_duplicate_feature_names_and_series_fail_fast() -> None:
    duplicate_name = _document()
    cpi_features = _target(duplicate_name, "CPILFESL")["features"]
    assert isinstance(cpi_features, list)
    copied = copy.deepcopy(cpi_features[0])
    copied["series_id"] = "A_DIFFERENT_SERIES"
    cpi_features.append(copied)
    with pytest.raises(TargetConfigError, match="duplicate feature names"):
        parse_target_config(duplicate_name)

    duplicate_series = _document()
    cpi_features = _target(duplicate_series, "CPILFESL")["features"]
    assert isinstance(cpi_features, list)
    copied = copy.deepcopy(cpi_features[0])
    copied["name"] = "otherwise_unique_feature_name"
    cpi_features.append(copied)
    with pytest.raises(TargetConfigError, match="duplicate feature series"):
        parse_target_config(duplicate_series)


def test_invalid_quarterly_dates_and_unsupported_transforms_fail_fast() -> None:
    bad_date = _document()
    evaluation = _target(bad_date, "GDPC1")["evaluation"]
    assert isinstance(evaluation, dict)
    evaluation["start"] = "2021-02-01"
    with pytest.raises(TargetConfigError, match="quarter starts"):
        parse_target_config(bad_date)

    bad_target_transform = _document()
    _target(bad_target_transform, "GDPC1")["transformation"] = "year_over_year"
    with pytest.raises(TargetConfigError, match="unsupported target transform"):
        parse_target_config(bad_target_transform)

    bad_feature_transform = _document()
    features = _target(bad_feature_transform, "PAYEMS")["features"]
    assert isinstance(features, list)
    features[0]["transformation"] = "future_change"
    with pytest.raises(TargetConfigError, match="unsupported feature transform"):
        parse_target_config(bad_feature_transform)


def test_loader_accepts_explicit_local_path_and_rejects_unknown_fields(tmp_path: Path) -> None:
    explicit_path = tmp_path / "targets.toml"
    explicit_path.write_text(DEFAULT_TARGET_CONFIG_PATH.read_text())
    assert load_target_config(explicit_path).source_path == explicit_path.resolve()

    document = _document()
    document["api_token"] = "must-not-be-accepted"
    with pytest.raises(TargetConfigError, match="unsupported fields: api_token"):
        parse_target_config(document)
