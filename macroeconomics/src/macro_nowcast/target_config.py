"""Strict typed configuration for the three synthetic nowcast targets."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date, datetime
from pathlib import Path
from typing import Literal, cast

from macro_nowcast.features import FeatureSpec

Frequency = Literal["daily", "weekly", "monthly", "quarterly"]
Transformation = Literal[
    "level",
    "difference",
    "percent_change",
    "log_change",
    "annualized_percent_change",
]
Aggregation = Literal["latest", "trailing_mean"]
Annualization = Literal["not_applicable", "nonannualized", "saar"]

SUPPORTED_FREQUENCIES = frozenset({"daily", "weekly", "monthly", "quarterly"})
SUPPORTED_TRANSFORMATIONS = frozenset(
    {"level", "difference", "percent_change", "log_change", "annualized_percent_change"}
)
SUPPORTED_AGGREGATIONS = frozenset({"latest", "trailing_mean"})
SUPPORTED_ANNUALIZATIONS = frozenset({"not_applicable", "nonannualized", "saar"})
FEATURE_SPEC_FIELD_NAMES = tuple(field.name for field in fields(FeatureSpec))

DEFAULT_TARGET_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "targets.toml"

_EXPECTED_TARGETS = {
    "PAYEMS": (
        "payems_change_mom_thousands",
        "monthly",
        "difference",
        "not_applicable",
        "thousands_of_persons_change_mom",
    ),
    "CPILFESL": (
        "core_cpi_pct_change_mom",
        "monthly",
        "percent_change",
        "nonannualized",
        "percent_change_mom_nonannualized",
    ),
    "GDPC1": (
        "real_gdp_pct_change_qoq_saar",
        "quarterly",
        "annualized_percent_change",
        "saar",
        "percent_change_qoq_saar",
    ),
}


class TargetConfigError(ValueError):
    """Raised when target configuration is ambiguous or internally inconsistent."""


def _nonempty_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TargetConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _integer(value: object, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TargetConfigError(f"{field} must be an integer")
    if value < minimum:
        raise TargetConfigError(f"{field} must be at least {minimum}")
    return value


def _date(value: object, *, field: str) -> date:
    if isinstance(value, datetime):
        raise TargetConfigError(f"{field} must be a date, not a datetime")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise TargetConfigError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TargetConfigError(f"{field} must be an ISO date") from exc


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TargetConfigError(f"{field} must be a table")
    if any(not isinstance(key, str) for key in value):
        raise TargetConfigError(f"{field} keys must be strings")
    return cast(Mapping[str, object], value)


def _sequence(value: object, *, field: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TargetConfigError(f"{field} must be an array")
    return cast(Sequence[object], value)


def _check_fields(
    values: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str] | None = None,
    context: str,
) -> None:
    optional = optional or set()
    missing = required.difference(values)
    unknown = set(values).difference(required | optional)
    if missing:
        raise TargetConfigError(f"{context} is missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise TargetConfigError(f"{context} has unsupported fields: {', '.join(sorted(unknown))}")


@dataclass(frozen=True, slots=True)
class ConfiguredFeatureSpec:
    """Feature declaration using the same field names as runtime ``FeatureSpec``.

    The configuration vocabulary additionally admits quarterly frequency and the
    explicit ``annualized_percent_change`` transform required by real GDP.  The
    execution layer can consume :meth:`as_feature_spec_kwargs` when it supports
    those values.
    """

    name: str
    series_id: str
    frequency: Frequency
    transformation: Transformation
    aggregation: Aggregation
    window: int | None = None
    lag_periods: int = 0

    def __post_init__(self) -> None:
        if not self.name or not self.series_id:
            raise TargetConfigError("feature name and series_id cannot be empty")
        if self.series_id != self.series_id.upper():
            raise TargetConfigError(f"feature series_id must be uppercase: {self.series_id}")
        if self.frequency not in SUPPORTED_FREQUENCIES:
            raise TargetConfigError(f"unsupported feature frequency: {self.frequency}")
        if self.transformation not in SUPPORTED_TRANSFORMATIONS:
            raise TargetConfigError(f"unsupported feature transform: {self.transformation}")
        if self.aggregation not in SUPPORTED_AGGREGATIONS:
            raise TargetConfigError(f"unsupported feature aggregation: {self.aggregation}")
        if self.lag_periods < 0:
            raise TargetConfigError("feature lag_periods cannot be negative")
        if self.frequency in {"daily", "weekly"} and self.lag_periods:
            raise TargetConfigError("daily and weekly features cannot use period lags")
        if self.aggregation == "trailing_mean":
            if self.window is None or self.window < 1:
                raise TargetConfigError("trailing_mean requires a positive window")
            if self.transformation != "level":
                raise TargetConfigError("trailing_mean currently supports only level values")
        elif self.window is not None:
            raise TargetConfigError("latest aggregation cannot define a window")
        if self.transformation == "annualized_percent_change" and self.frequency != "quarterly":
            raise TargetConfigError(
                "annualized_percent_change is supported only for quarterly features"
            )

    def as_feature_spec_kwargs(self) -> dict[str, object]:
        """Return fields named exactly like ``macro_nowcast.features.FeatureSpec``."""

        values: dict[str, object] = {
            "name": self.name,
            "series_id": self.series_id,
            "frequency": self.frequency,
            "transformation": self.transformation,
            "aggregation": self.aggregation,
            "window": self.window,
            "lag_periods": self.lag_periods,
        }
        if tuple(values) != FEATURE_SPEC_FIELD_NAMES:
            raise AssertionError("configured feature fields drifted from runtime FeatureSpec")
        return values

    @property
    def runtime_feature_spec_supported(self) -> bool:
        """Whether the current runtime FeatureSpec can execute this declaration."""

        return True

    def to_feature_spec(self) -> FeatureSpec:
        """Convert configurations supported by the current feature execution layer."""

        return FeatureSpec(**self.as_feature_spec_kwargs())  # type: ignore[arg-type]


# Concise alias for callers that do not need to distinguish runtime/config specs.
FeatureConfig = ConfiguredFeatureSpec


@dataclass(frozen=True, slots=True)
class EvaluationWindow:
    start: date
    end: date
    latest_vintage: date
    minimum_train_periods: int

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise TargetConfigError("evaluation end cannot precede start")
        if self.latest_vintage < self.end:
            raise TargetConfigError("latest_vintage cannot precede evaluation end")
        if self.minimum_train_periods < 1:
            raise TargetConfigError("minimum_train_periods must be positive")


@dataclass(frozen=True, slots=True)
class TargetDefinition:
    series_id: str
    name: str
    frequency: Literal["monthly", "quarterly"]
    transformation: Literal["difference", "percent_change", "annualized_percent_change"]
    annualization: Annualization
    units: str
    horizon: int
    evaluation: EvaluationWindow
    features: tuple[ConfiguredFeatureSpec, ...]
    provenance_label: str

    def __post_init__(self) -> None:
        if not self.name or not self.units:
            raise TargetConfigError("target name and units cannot be empty")
        if self.series_id != self.series_id.upper():
            raise TargetConfigError(f"target series_id must be uppercase: {self.series_id}")
        if self.frequency not in {"monthly", "quarterly"}:
            raise TargetConfigError(f"unsupported target frequency: {self.frequency}")
        if self.transformation not in {
            "difference",
            "percent_change",
            "annualized_percent_change",
        }:
            raise TargetConfigError(f"unsupported target transform: {self.transformation}")
        if self.annualization not in SUPPORTED_ANNUALIZATIONS:
            raise TargetConfigError(f"unsupported annualization: {self.annualization}")
        if self.transformation == "difference" and self.annualization != "not_applicable":
            raise TargetConfigError("difference targets must use annualization='not_applicable'")
        if self.transformation == "percent_change" and self.annualization != "nonannualized":
            raise TargetConfigError(
                "percent_change targets must explicitly use annualization='nonannualized'"
            )
        if self.transformation == "annualized_percent_change" and (
            self.frequency != "quarterly" or self.annualization != "saar"
        ):
            raise TargetConfigError(
                "annualized_percent_change requires quarterly frequency "
                "and annualization='saar'"
            )
        if self.frequency == "monthly":
            dates_are_valid = self.evaluation.start.day == self.evaluation.end.day == 1
        else:
            dates_are_valid = (
                self.evaluation.start.day == self.evaluation.end.day == 1
                and self.evaluation.start.month in {1, 4, 7, 10}
                and self.evaluation.end.month in {1, 4, 7, 10}
            )
        if not dates_are_valid:
            expected = "month starts" if self.frequency == "monthly" else "quarter starts"
            raise TargetConfigError(f"{self.series_id} evaluation dates must be {expected}")
        if not 1 <= len(self.features) <= 10:
            raise TargetConfigError("each target requires between one and ten features")
        feature_names = [feature.name for feature in self.features]
        feature_series = [feature.series_id for feature in self.features]
        if len(feature_names) != len(set(feature_names)):
            raise TargetConfigError(f"duplicate feature names for target {self.series_id}")
        if len(feature_series) != len(set(feature_series)):
            raise TargetConfigError(f"duplicate feature series for target {self.series_id}")
        if self.series_id not in feature_series:
            raise TargetConfigError(
                f"target {self.series_id} must include an autoregressive feature"
            )
        if self.provenance_label != "synthetic_fixture":
            raise TargetConfigError("default targets must retain synthetic_fixture provenance")

    @property
    def target_name(self) -> str:
        return self.name

    @property
    def target_units(self) -> str:
        return self.units

    @property
    def annualization_factor(self) -> int | None:
        return 4 if self.annualization == "saar" else None

    @property
    def formula(self) -> str:
        if self.transformation == "difference":
            return "current_level - prior_level"
        if self.transformation == "percent_change":
            return "100 * (current_level / prior_level - 1)"
        return "100 * ((current_level / prior_level) ** 4 - 1)"

    @property
    def evaluation_start(self) -> date:
        return self.evaluation.start

    @property
    def evaluation_end(self) -> date:
        return self.evaluation.end

    @property
    def latest_vintage(self) -> date:
        return self.evaluation.latest_vintage

    @property
    def minimum_train_periods(self) -> int:
        return self.evaluation.minimum_train_periods

    def to_target_spec(self):
        """Convert to the executable ``targets.TargetSpec`` without changing formulas."""

        from macro_nowcast.targets import TargetSpec

        transformation = {
            "difference": "difference",
            "percent_change": "arithmetic_percent_change",
            "annualized_percent_change": "compounded_percent_change",
        }[self.transformation]
        return TargetSpec(
            series_id=self.series_id,
            target_name=self.name,
            target_units=self.units,
            frequency=self.frequency,
            transformation=transformation,  # type: ignore[arg-type]
            annualization_factor=self.annualization_factor,
        )


TargetConfig = TargetDefinition


@dataclass(frozen=True, slots=True)
class TargetConfigSet:
    schema_version: int
    provenance_label: str
    data_mode: str
    is_default: bool
    targets: tuple[TargetDefinition, ...]
    source_path: Path | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise TargetConfigError("unsupported target-config schema_version")
        if self.provenance_label != "synthetic_fixture" or self.data_mode != "synthetic_fixture":
            raise TargetConfigError("default configuration must be explicitly synthetic_fixture")
        if self.is_default is not True:
            raise TargetConfigError("default configuration must set is_default=true")
        series_ids = [target.series_id for target in self.targets]
        names = [target.name for target in self.targets]
        if len(series_ids) != len(set(series_ids)):
            raise TargetConfigError("duplicate target series_id")
        if len(names) != len(set(names)):
            raise TargetConfigError("duplicate target name")
        expected = set(_EXPECTED_TARGETS)
        if set(series_ids) != expected:
            raise TargetConfigError(
                f"target series must be exactly: {', '.join(sorted(expected))}"
            )
        for target in self.targets:
            expected_definition = _EXPECTED_TARGETS[target.series_id]
            actual = (
                target.name,
                target.frequency,
                target.transformation,
                target.annualization,
                target.units,
            )
            if actual != expected_definition:
                raise TargetConfigError(
                    f"{target.series_id} target definition is ambiguous or unsupported"
                )

    def get(self, series_id: str) -> TargetDefinition:
        """Return one target by case-insensitive series identifier."""

        normalized = series_id.upper()
        for target in self.targets:
            if target.series_id == normalized:
                return target
        raise KeyError(series_id)

    def get_by_name(self, name: str) -> TargetDefinition:
        for target in self.targets:
            if target.name == name:
                return target
        raise KeyError(name)

    @property
    def by_series(self) -> Mapping[str, TargetDefinition]:
        return {target.series_id: target for target in self.targets}


TargetRegistry = TargetConfigSet


def _parse_feature(raw: object, *, target_series_id: str, index: int) -> ConfiguredFeatureSpec:
    context = f"target {target_series_id} feature {index}"
    values = _mapping(raw, field=context)
    required = {"name", "series_id", "frequency", "transformation", "aggregation"}
    optional = {"window", "lag_periods"}
    _check_fields(values, required=required, optional=optional, context=context)
    frequency = _nonempty_text(values["frequency"], field=f"{context}.frequency")
    transformation = _nonempty_text(
        values["transformation"], field=f"{context}.transformation"
    )
    aggregation = _nonempty_text(values["aggregation"], field=f"{context}.aggregation")
    if frequency not in SUPPORTED_FREQUENCIES:
        raise TargetConfigError(f"unsupported feature frequency: {frequency}")
    if transformation not in SUPPORTED_TRANSFORMATIONS:
        raise TargetConfigError(f"unsupported feature transform: {transformation}")
    if aggregation not in SUPPORTED_AGGREGATIONS:
        raise TargetConfigError(f"unsupported feature aggregation: {aggregation}")
    window = values.get("window")
    parsed_window = (
        None
        if window is None
        else _integer(window, field=f"{context}.window", minimum=1)
    )
    return ConfiguredFeatureSpec(
        name=_nonempty_text(values["name"], field=f"{context}.name"),
        series_id=_nonempty_text(values["series_id"], field=f"{context}.series_id"),
        frequency=cast(Frequency, frequency),
        transformation=cast(Transformation, transformation),
        aggregation=cast(Aggregation, aggregation),
        window=parsed_window,
        lag_periods=_integer(
            values.get("lag_periods", 0), field=f"{context}.lag_periods"
        ),
    )


def _parse_evaluation(raw: object, *, target_series_id: str) -> EvaluationWindow:
    context = f"target {target_series_id} evaluation"
    values = _mapping(raw, field=context)
    required = {"start", "end", "latest_vintage", "minimum_train_periods"}
    _check_fields(values, required=required, context=context)
    return EvaluationWindow(
        start=_date(values["start"], field=f"{context}.start"),
        end=_date(values["end"], field=f"{context}.end"),
        latest_vintage=_date(values["latest_vintage"], field=f"{context}.latest_vintage"),
        minimum_train_periods=_integer(
            values["minimum_train_periods"],
            field=f"{context}.minimum_train_periods",
            minimum=1,
        ),
    )


def _parse_target(raw: object, *, provenance_label: str, index: int) -> TargetDefinition:
    context = f"target {index}"
    values = _mapping(raw, field=context)
    required = {
        "series_id",
        "name",
        "frequency",
        "transformation",
        "annualization",
        "units",
        "horizon",
        "evaluation",
        "features",
    }
    _check_fields(values, required=required, context=context)
    series_id = _nonempty_text(values["series_id"], field=f"{context}.series_id")
    frequency = _nonempty_text(values["frequency"], field=f"{context}.frequency")
    transformation = _nonempty_text(
        values["transformation"], field=f"{context}.transformation"
    )
    annualization = _nonempty_text(values["annualization"], field=f"{context}.annualization")
    feature_rows = _sequence(values["features"], field=f"{context}.features")
    features_config = tuple(
        _parse_feature(feature, target_series_id=series_id, index=feature_index)
        for feature_index, feature in enumerate(feature_rows, start=1)
    )
    return TargetDefinition(
        series_id=series_id,
        name=_nonempty_text(values["name"], field=f"{context}.name"),
        frequency=cast(Literal["monthly", "quarterly"], frequency),
        transformation=cast(
            Literal["difference", "percent_change", "annualized_percent_change"],
            transformation,
        ),
        annualization=cast(Annualization, annualization),
        units=_nonempty_text(values["units"], field=f"{context}.units"),
        horizon=_integer(values["horizon"], field=f"{context}.horizon"),
        evaluation=_parse_evaluation(values["evaluation"], target_series_id=series_id),
        features=features_config,
        provenance_label=provenance_label,
    )


def parse_target_config(
    document: Mapping[str, object],
    *,
    source_path: Path | None = None,
) -> TargetConfigSet:
    """Validate a decoded TOML document without consulting environment variables."""

    _check_fields(
        document,
        required={"schema_version", "defaults", "targets"},
        context="target configuration",
    )
    defaults = _mapping(document["defaults"], field="defaults")
    _check_fields(
        defaults,
        required={"provenance_label", "data_mode", "is_default"},
        context="defaults",
    )
    provenance_label = _nonempty_text(
        defaults["provenance_label"], field="defaults.provenance_label"
    )
    data_mode = _nonempty_text(defaults["data_mode"], field="defaults.data_mode")
    is_default = defaults["is_default"]
    if not isinstance(is_default, bool):
        raise TargetConfigError("defaults.is_default must be a boolean")
    target_rows = _sequence(document["targets"], field="targets")
    targets = tuple(
        _parse_target(target, provenance_label=provenance_label, index=index)
        for index, target in enumerate(target_rows, start=1)
    )
    return TargetConfigSet(
        schema_version=_integer(document["schema_version"], field="schema_version", minimum=1),
        provenance_label=provenance_label,
        data_mode=data_mode,
        is_default=is_default,
        targets=targets,
        source_path=source_path,
    )


def load_target_config(path: str | Path | None = None) -> TargetConfigSet:
    """Load the repository target config (or an explicit local TOML path)."""

    resolved = DEFAULT_TARGET_CONFIG_PATH if path is None else Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"target configuration does not exist: {resolved}")
    try:
        with resolved.open("rb") as handle:
            document = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise TargetConfigError(f"invalid TOML in target configuration: {resolved}") from exc
    return parse_target_config(document, source_path=resolved)


__all__ = [
    "DEFAULT_TARGET_CONFIG_PATH",
    "FEATURE_SPEC_FIELD_NAMES",
    "Aggregation",
    "Annualization",
    "ConfiguredFeatureSpec",
    "EvaluationWindow",
    "FeatureConfig",
    "Frequency",
    "TargetConfig",
    "TargetConfigError",
    "TargetConfigSet",
    "TargetDefinition",
    "TargetRegistry",
    "Transformation",
    "load_target_config",
    "parse_target_config",
]
