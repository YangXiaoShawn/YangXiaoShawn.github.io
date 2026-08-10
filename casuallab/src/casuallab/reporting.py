"""Generate auditable Markdown decision artifacts from computed outputs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

from casuallab.estimands import get_estimand

_EXPECTED_POLICY_NAMES = frozenset(
    {"no_treatment", "random", "uniform", "rule_based", "model_based"}
)


def _strict_boolean(series: pd.Series, name: str) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        if series.isna().any():
            raise ValueError(f"{name} contains missing values")
        return series.astype(bool)
    normalized = series.astype(str).str.strip().str.lower()
    mapping = {"true": True, "false": False, "1": True, "0": False}
    invalid = ~normalized.isin(mapping)
    if invalid.any():
        raise ValueError(f"{name} must contain explicit booleans")
    return normalized.map(mapping).astype(bool)


def _validate_policy_provenance(policy: pd.DataFrame) -> tuple[set[int], set[int]]:
    """Fail closed when policy rows cannot be shown to share one holdout contract."""

    required = {
        "policy",
        "training_markets",
        "holdout_markets",
        "training_market_seeds",
        "holdout_market_seeds",
        "target_estimand",
        "target_population_id",
        "n_zones",
        "n_periods",
        "weighting",
        "simulation_config",
        "policy_config",
    }
    missing = required.difference(policy.columns)
    if missing:
        raise ValueError(f"policy provenance missing columns: {sorted(missing)}")
    names = policy["policy"].astype(str)
    if names.duplicated().any() or set(names) != _EXPECTED_POLICY_NAMES:
        raise ValueError(
            "policy artifact must contain exactly one row for every predeclared baseline "
            "and learned policy"
        )
    consistent = required.difference({"policy"})
    inconsistent = [
        column for column in sorted(consistent) if policy[column].nunique(dropna=False) != 1
    ]
    if inconsistent:
        raise ValueError(f"policy provenance differs across rows: {inconsistent}")
    try:
        train_seeds = set(json.loads(str(policy["training_market_seeds"].iloc[0])))
        holdout_seeds = set(json.loads(str(policy["holdout_market_seeds"].iloc[0])))
        training_markets = int(policy["training_markets"].iloc[0])
        holdout_markets = int(policy["holdout_markets"].iloc[0])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("policy seed/count provenance is malformed") from exc
    if len(train_seeds) != training_markets or len(holdout_seeds) != holdout_markets:
        raise ValueError("policy seed counts do not match declared market counts")
    if train_seeds.intersection(holdout_seeds):
        raise ValueError("policy training and holdout seeds overlap")
    if policy["target_estimand"].iloc[0] != "full_horizon_incremental_trips":
        raise ValueError("policy artifact has an unsupported target estimand")
    return train_seeds, holdout_seeds


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _format_value(value: object) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.4f}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def markdown_table(frame: pd.DataFrame, columns: Iterable[str]) -> str:
    selected = list(columns)
    missing = set(selected).difference(frame.columns)
    if missing:
        raise ValueError(f"table columns missing: {sorted(missing)}")
    header = "| " + " | ".join(selected) + " |"
    separator = "|" + "|".join(["---"] * len(selected)) + "|"
    rows = [
        "| " + " | ".join(_format_value(value) for value in row) + " |"
        for row in frame[selected].itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *rows])


def choose_recommendation(
    benchmark: pd.DataFrame,
    target_estimand: str,
    *,
    require_declared_scenarios: bool = True,
) -> pd.Series:
    """Choose a safe design, optionally within an already matched scenario subset.

    Reports use the strict default and require every declared sensitivity scenario.
    A decision interface may set ``require_declared_scenarios=False`` only after it
    has independently validated the complete artifact and exactly matched all
    causally relevant controls for the displayed scenario.
    """
    required = {
        "design",
        "estimator",
        "target_estimand",
        "rmse",
        "coverage",
        "power",
        "bias",
        "identified",
        "inference_valid",
        "fit_complete",
        "applicable",
        "attempted_fits",
        "successful_fits",
    }
    missing = required.difference(benchmark.columns)
    if missing:
        raise ValueError(f"benchmark results missing columns: {sorted(missing)}")
    relevant = benchmark.loc[benchmark["target_estimand"] == target_estimand].copy()
    if relevant.empty:
        raise ValueError(f"no generated result targets {target_estimand!r}")
    compatible_designs = set(get_estimand(target_estimand).compatible_designs)
    relevant = relevant.loc[relevant["design"].isin(compatible_designs)]
    if relevant.empty:
        raise ValueError(
            f"no benchmark rows use a design compatible with {target_estimand!r}"
        )

    for column in ("identified", "inference_valid", "fit_complete", "applicable"):
        relevant[column] = _strict_boolean(relevant[column], column)
    scenario_column = "scenario" if "scenario" in relevant else None
    observed_scenarios = (
        set(relevant[scenario_column].dropna().astype(str))
        if scenario_column is not None
        else {"single_scenario"}
    )
    if "declared_scenario_set" in relevant:
        declarations = relevant["declared_scenario_set"].dropna().astype(str).unique()
        if len(declarations) != 1:
            raise ValueError("benchmark rows do not share one declared scenario set")
        try:
            parsed_scenarios = json.loads(declarations[0])
        except json.JSONDecodeError as exc:
            raise ValueError("declared scenario set is malformed JSON") from exc
        if not isinstance(parsed_scenarios, list) or not all(
            isinstance(item, str) and item for item in parsed_scenarios
        ):
            raise ValueError("declared scenario set must be a nonempty JSON string list")
        declared_scenarios = set(parsed_scenarios)
        if not declared_scenarios or not observed_scenarios.issubset(declared_scenarios):
            raise ValueError("observed benchmark rows are outside the declared scenario set")
        if require_declared_scenarios and observed_scenarios != declared_scenarios:
            raise ValueError("observed benchmark rows do not cover the declared scenario set")
        if "declared_scenario_count" in relevant:
            counts = pd.to_numeric(relevant["declared_scenario_count"], errors="coerce")
            if counts.isna().any() or not counts.eq(len(declared_scenarios)).all():
                raise ValueError("declared scenario count is inconsistent")
    else:
        declared_scenarios = observed_scenarios
    evaluated_scenarios = (
        declared_scenarios if require_declared_scenarios else observed_scenarios
    )
    eligible_groups: list[pd.DataFrame] = []
    for _, group in relevant.groupby(["design", "estimator"], dropna=False, sort=True):
        present_scenarios = (
            set(group[scenario_column].dropna().astype(str))
            if scenario_column is not None
            else {"single_scenario"}
        )
        identified_everywhere = bool(group["identified"].all())
        valid_inference_everywhere = bool(group["inference_valid"].all())
        complete_everywhere = bool(
            group["applicable"].all()
            and (group["attempted_fits"] > 0).all()
            and group["fit_complete"].all()
            and (group["attempted_fits"] == group["successful_fits"]).all()
        )
        nominal = (
            group["confidence_level"]
            if "confidence_level" in group
            else pd.Series(0.95, index=group.index)
        )
        coverage_mcse = (
            group["coverage_mcse"].fillna(0.0)
            if "coverage_mcse" in group
            else pd.Series(0.0, index=group.index)
        )
        # Coverage must be plausibly within ten percentage points of nominal after
        # allowing two Monte Carlo standard errors. Precision cannot compensate for
        # catastrophically invalid uncertainty.
        coverage_valid_everywhere = bool(
            (group["coverage"] + 2.0 * coverage_mcse >= nominal - 0.10).all()
        )
        if (
            present_scenarios == evaluated_scenarios
            and identified_everywhere
            and valid_inference_everywhere
            and complete_everywhere
            and coverage_valid_everywhere
        ):
            eligible_groups.append(group)
    if not eligible_groups:
        scenario_scope = (
            "the full declared scenario set"
            if require_declared_scenarios
            else "the exact matched scenario subset"
        )
        raise ValueError(
            "no design-estimator pair has complete fits and is identified with valid "
            f"inference across {scenario_scope}"
        )
    eligible = pd.concat(eligible_groups, ignore_index=False)
    eligible = eligible.loc[
        np.isfinite(eligible["bias"])
        & np.isfinite(eligible["rmse"])
        & np.isfinite(eligible["coverage"])
        & np.isfinite(eligible["power"])
    ].copy()
    if eligible.empty:
        raise ValueError("no robust candidate has finite decision metrics")
    finite_scenarios = (
        set(eligible[scenario_column].dropna().astype(str))
        if scenario_column is not None
        else {"single_scenario"}
    )
    if finite_scenarios != evaluated_scenarios:
        raise ValueError("finite decision metrics do not cover the evaluated scenario set")

    nominal = (
        eligible["confidence_level"] if "confidence_level" in eligible else pd.Series(0.95, index=eligible.index)
    )
    eligible["coverage_gap"] = (eligible["coverage"] - nominal).abs()
    # RMSE is primary; a large coverage failure is explicitly penalized rather than
    # hidden behind a single precision statistic. When the file contains a
    # sensitivity grid, choose on each pair's worst configured scenario instead of
    # opportunistically selecting the easiest row.
    eligible["decision_score"] = eligible["rmse"] * (1.0 + 2.0 * eligible["coverage_gap"])
    pair_columns = ["design", "estimator"]
    worst_indices = eligible.groupby(pair_columns, dropna=False)["decision_score"].idxmax()
    robust_candidates = eligible.loc[worst_indices].copy()
    robust_candidates["selection_rule"] = (
        "among complete identified fits passing the coverage gate, minimize "
        "worst-scenario RMSE with coverage penalty"
        if require_declared_scenarios
        else "within the exact matched scenario subset, among complete identified fits "
        "passing the coverage gate, minimize worst-scenario RMSE with coverage penalty"
    )
    robust_candidates["declared_scenarios"] = len(declared_scenarios)
    robust_candidates["evaluated_scenarios"] = len(evaluated_scenarios)
    robust_candidates["recommendation_scope"] = (
        "declared_sensitivity_set"
        if require_declared_scenarios
        else "selected_scenario_conditional"
    )
    robust_candidates["unmatched_declared_scenarios"] = json.dumps(
        sorted(declared_scenarios.difference(evaluated_scenarios)),
        separators=(",", ":"),
    )
    return robust_candidates.sort_values(
        ["decision_score", "coverage_gap", "power", "design", "estimator"],
        ascending=[True, True, False, True, True],
    ).iloc[0]


def design_limitations(design: str) -> str:
    """Return the operational and identification caveat for a design family."""

    limitations = {
        "individual": (
            "Requires negligible cross-unit interference or a correct exposure model; "
            "market reallocation can make the individual contrast differ from total marketplace impact."
        ),
        "geo_cluster": (
            "Needs enough independent geographic clusters and limited leakage across boundaries; "
            "cluster-level uncertainty is unreliable with very few treated clusters."
        ),
        "time_block": (
            "Vulnerable to time shocks and persistence across block boundaries; use predeclared blocks, "
            "time controls, and a washout supported by sensitivity analysis."
        ),
        "switchback": (
            "Relies on a credible washout and stable time pattern; carryover or anticipatory behavior can "
            "contaminate subsequent periods."
        ),
        "geo_time": (
            "Needs two-way cluster-aware inference and explicit spatial/temporal exposure mapping; "
            "operational complexity may reduce compliance."
        ),
        "geo_time_clustered": (
            "Needs two-way cluster-aware inference and explicit spatial/temporal exposure mapping; "
            "operational complexity may reduce compliance."
        ),
    }
    return limitations.get(
        design,
        "Validate assignment integrity, exposure mapping, effective sample size, and interference sensitivity.",
    )


def generate_decision_appendix(
    benchmark_path: str | Path,
    *,
    output_path: str | Path,
    policy_path: str | Path | None = None,
    target_estimand: str | None = None,
) -> Path:
    """Generate a Markdown appendix using only computed CSV quantities."""

    benchmark_file = Path(benchmark_path)
    benchmark = pd.read_csv(benchmark_file)
    if benchmark.empty:
        raise ValueError("benchmark results are empty")
    if "evidence_type" not in benchmark:
        raise ValueError("benchmark results must label evidence_type")
    if not benchmark["evidence_type"].astype(str).str.startswith("semi_synthetic").all():
        raise ValueError("benchmark results contain unlabeled or non-simulation causal claims")

    available_estimands = sorted(benchmark["target_estimand"].dropna().astype(str).unique())
    selected_estimand = target_estimand or available_estimands[0]
    recommendation_error: str | None = None
    try:
        recommendation = choose_recommendation(benchmark, selected_estimand)
    except ValueError as exc:
        recommendation = None
        recommendation_error = str(exc)
    relevant = benchmark.loc[benchmark["target_estimand"] == selected_estimand].copy()
    table_columns = [
        column
        for column in (
            "scenario",
            "spillover_strength",
            "persistence",
            "treatment_duration",
            "washout_periods",
            "configured_geo_clusters",
            "effective_randomization_clusters",
            "cluster_semantics",
            "budget_scope",
            "design",
            "estimator",
            "comparison_status",
            "bias",
            "rmse",
            "coverage",
            "power",
            "mean_std_error",
            "normalized_precision_cost",
            "identified",
            "inference_valid",
            "attempted_fits",
            "successful_fits",
            "failed_fits",
            "fit_complete",
        )
        if column in relevant
    ]

    policy_section = (
        "Policy results were not supplied. Run the policy benchmark before making an allocation recommendation."
    )
    policy_hash_line = ""
    if policy_path is not None:
        policy_file = Path(policy_path)
        policy = pd.read_csv(policy_file)
        required_policy = {
            "policy",
            "expected_incremental_outcome",
            "incremental_outcome_se",
            "incremental_outcome_p10",
            "budget_spent",
            "budget_efficiency",
            "budget_feasible",
            "evaluation_complete",
            "policy_eligible",
            "decision_instability",
            "training_market_seeds",
            "holdout_market_seeds",
            "training_signal",
            "evaluation_engine",
            "planning_cost_basis",
            "target_estimand",
            "evidence_type",
            "training_markets",
            "holdout_markets",
            "target_population_id",
            "n_zones",
            "n_periods",
            "weighting",
            "simulation_config",
            "policy_config",
        }
        missing = required_policy.difference(policy.columns)
        if missing:
            raise ValueError(f"policy results missing columns: {sorted(missing)}")
        if not policy["evidence_type"].astype(str).str.startswith("semi_synthetic").all():
            raise ValueError("policy results must be labeled semi-synthetic")
        for column in ("budget_feasible", "evaluation_complete", "policy_eligible"):
            policy[column] = _strict_boolean(policy[column], column)
        if not policy["training_signal"].astype(str).str.contains(
            "no structural truth"
        ).all():
            raise ValueError("policy artifact does not establish truth-free training")
        if not policy["evaluation_engine"].astype(str).str.contains("simulator rerun").all():
            raise ValueError("policy artifact does not establish simulator evaluation")
        if not policy["planning_cost_basis"].astype(str).str.contains(
            "no treated holdout"
        ).all():
            raise ValueError("policy artifact uses an unsafe holdout cost basis")
        _validate_policy_provenance(policy)
        display = policy.loc[
            policy["budget_feasible"]
            & policy["evaluation_complete"]
            & policy["policy_eligible"]
        ].sort_values(
            ["incremental_outcome_p10", "decision_instability", "policy"],
            ascending=[False, True, True],
        )
        policy_section = markdown_table(
            display,
            [
                "policy",
                "expected_incremental_outcome",
                "incremental_outcome_se",
                "incremental_outcome_p10",
                "budget_spent",
                "budget_efficiency",
                "mean_model_instability",
                "decision_instability",
            ],
        )
        policy_hash_line = f"- Policy SHA-256: `{sha256_file(policy_file)}`\n"

    if recommendation is None:
        recommendation_section = (
            "No design-estimator pair is recommended because none has complete fits and "
            "remains identified with valid inference across every declared sensitivity "
            "scenario. This is an "
            f"informative design gap, not a tie: {_format_value(recommendation_error)}."
        )
    else:
        recommendation_section = (
            "Among the simulated candidates for this estimand, the predeclared selection "
            f"rule—{recommendation['selection_rule']}—chooses **{recommendation['design']}** "
            f"assignment with **{recommendation['estimator']}** estimation. The displayed "
            "selection row is that pair's adverse configured scenario: generated bias "
            f"{_format_value(recommendation['bias'])}, RMSE {_format_value(recommendation['rmse'])}, "
            f"interval coverage {_format_value(recommendation['coverage'])}, and power "
            f"{_format_value(recommendation['power'])}.\n\n"
            "This is conditional on the configured data-generating process and the selection "
            "score documented in `src/casuallab/reporting.py`. It is not a universal design "
            f"recommendation.\n\nPrimary limitation: "
            f"{design_limitations(str(recommendation['design']))}"
        )

    text = f"""# Generated Decision Appendix

> Evidence type: **semi-synthetic causal benchmark**. Numerical values below are generated by code against known simulator truth. They are not treatment effects estimated from public trip records and are not a promise of production impact.

## Selected estimand

`{selected_estimand}`

## Design and estimator comparison

{markdown_table(relevant.sort_values(["design", "estimator"]), table_columns)}

## Conditional recommendation

{recommendation_section}

## Honest-holdout budget policy comparison

{policy_section}

## Reproducibility metadata

- Benchmark SHA-256: `{sha256_file(benchmark_file)}`
{policy_hash_line}- Generated from machine-readable outputs; no numerical result is embedded in this template.

## Required operational checks

- Confirm the assignment unit can be enforced and noncompliance is measured.
- Predeclare the exposure mapping, primary estimand, metric, inference unit, and stopping rule.
- Run spillover, persistence, washout, and cluster-count sensitivity analyses.
- Check budget delivery, displacement across untreated zones/times, rider welfare, driver welfare, and service quality.
- Re-estimate only after validating randomization and logging integrity.
"""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    return destination
