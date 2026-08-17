#!/usr/bin/env python
"""Estimate tariff incidence: the model ladder, event studies, PPML and placebos.

    python scripts/estimate_incidence.py [--config sample_slice.yaml]

Writes tidy result tables to ``data/results/`` with a run stamp attached to every
one, so any number in a report can be traced back to a configuration and commit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

from tariff_incidence.config import load_config  # noqa: E402
from tariff_incidence.econ.designs import (  # noqa: E402
    descriptive_event_means,
    event_study,
    ppml_trade_flow,
    pretrend_test,
    stacked_event_study,
    two_way_fe_regression,
)
from tariff_incidence.panel.build import stable_code_sample  # noqa: E402
from tariff_incidence.paths import ensure_layers, layer_path  # noqa: E402
from tariff_incidence.provenance import DataProvenance, RunStamp  # noqa: E402

# Outcomes are labelled so a reader can never confuse a tariff-exclusive customs
# unit value with a duty-inclusive landed cost.
OUTCOMES = {
    "log_customs_unit_value": (
        "log customs unit value (TARIFF-EXCLUSIVE; foreign border price proxy, "
        "not a transaction price)"
    ),
    "log_landed_unit_value": (
        "log landed unit value (DUTY-INCLUSIVE, excludes freight; U.S. importer border cost)"
    ),
    "log_quantity": "log import quantity (primary quantity unit)",
    "log_customs_value": "log customs value",
}


def _stamp(cfg, provenance: DataProvenance) -> RunStamp:
    return RunStamp.create(
        config_name=cfg.config_name,
        config_bytes=cfg.raw_bytes,
        data_provenance=provenance,
        data_period_start=cfg.sample.start_month,
        data_period_end=cfg.sample.end_month,
    )


def _write(df: pl.DataFrame, name: str, stamp: RunStamp) -> Path:
    out = layer_path("results", f"{name}.parquet")
    df.with_columns(
        pl.lit(stamp.run_id).alias("run_id"),
        pl.lit(stamp.git_commit).alias("git_commit"),
        pl.lit(stamp.config_name).alias("config"),
        pl.lit(stamp.data_provenance.value).alias("data_provenance"),
        pl.lit(f"{stamp.data_period_start}..{stamp.data_period_end}").alias("data_period"),
    ).write_parquet(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="sample_slice.yaml")
    args = ap.parse_args()
    ensure_layers()

    cfg = load_config(args.config)
    panel = pl.read_parquet(layer_path("analytical", "trade_panel.parquet"))
    prov_raw = json.loads(
        (layer_path("analytical", "trade_panel.runstamp.json")).read_text()
    )["data_provenance"]
    provenance = DataProvenance(prov_raw)
    stamp = _stamp(cfg, provenance)

    print(stamp.banner())
    print(f"panel: {panel.height:,} rows, {panel['hs6'].n_unique()} products, "
          f"{panel['country_code'].n_unique()} countries")

    est = cfg.estimation
    window = (-est.event_window_pre, est.event_window_post)
    cluster = est.cluster_on
    all_rows: list[dict] = []
    spec_rows: list[dict] = []
    diagnostics: dict = {}
    stable_meta: dict = {}

    # ---------------------------------------------------------------- #
    # Rung 1: descriptive event-time means (no causal content)
    # ---------------------------------------------------------------- #
    for outcome in ["log_customs_unit_value", "log_landed_unit_value", "log_quantity"]:
        d = descriptive_event_means(panel, outcome, window=window)
        _write(d.with_columns(pl.lit(outcome).alias("outcome")), f"descriptive_means_{outcome}", stamp)
    print("rung 1: descriptive event-time means written")

    # ---------------------------------------------------------------- #
    # Rung 2: two-way FE regressions
    # ---------------------------------------------------------------- #
    # Estimand: effect on the *level* of a flow's outcome. Product-time effects
    # are deliberately NOT included here -- they would absorb the product-level
    # tariff shock we are trying to measure.
    fe_flow_time = ["flow_id", "month_key"]
    for outcome in OUTCOMES:
        fit, spec = two_way_fe_regression(
            panel,
            outcome,
            "additional_tariff_rate",
            fixed_effects=fe_flow_time,
            cluster_vars=cluster,
        )
        rows = fit.to_rows()
        for r in rows:
            r["outcome"] = outcome
            r["outcome_label"] = OUTCOMES[outcome]
            r["rung"] = "2_twfe"
        all_rows.extend(rows)
        spec_rows.append(spec.to_row() | {"rung": "2_twfe"})
        b = fit.params["additional_tariff_rate"]
        lo, hi = fit.conf_int("additional_tariff_rate")
        print(f"rung 2 [{outcome:>28}] beta={b:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]  "
              f"n={fit.n_obs:,}  clusters={fit.n_clusters}")

    # ---------------------------------------------------------------- #
    # Rung 3: event studies (the pre-trend test lives here)
    # ---------------------------------------------------------------- #
    # Two reference periods are run deliberately. t = -1 is the conventional
    # choice, but it is the month most exposed to front-running ahead of a known
    # effective date: if importers pull shipments forward, the reference period
    # is itself treated and every coefficient is shifted. t = -3 is far enough
    # back to sit outside the usual anticipation window. Disagreement between
    # the two is diagnostic, not a nuisance, so both are reported.
    for outcome in ["log_customs_unit_value", "log_landed_unit_value", "log_quantity"]:
        for ref in sorted({est.reference_event_time, -3}):
            fit, spec, coefs = event_study(
                panel,
                outcome,
                fixed_effects=fe_flow_time,
                cluster_vars=cluster,
                window=window,
                reference=ref,
            )
            tag = f"{outcome}_ref{abs(ref)}"
            _write(
                coefs.with_columns(
                    pl.lit(outcome).alias("outcome"), pl.lit(ref).alias("reference_period")
                ),
                f"event_study_{tag}",
                stamp,
            )
            pt = pretrend_test(coefs, fit)
            pt["reference_period"] = ref
            diagnostics[f"pretrend_{tag}"] = pt
            spec_rows.append(
                spec.to_row() | {"rung": "3_event_study", "reference_period": ref}
            )
            print(
                f"rung 3 [{outcome:>28} ref={ref:>2}] pre-trend: "
                f"max|b|={pt.get('max_abs_pre_coef', float('nan')):.4f} "
                f"approx p={pt.get('approx_p_value', float('nan')):.3f} "
                f"any_pre_sig_5pct={pt.get('any_pre_significant_5pct')}"
            )

    # ---------------------------------------------------------------- #
    # Rung 4: stacked multi-wave design
    # ---------------------------------------------------------------- #
    # The single-wave event study above cannot separate treatment dynamics from
    # treated-group-specific time variation, because with one effective date
    # event time IS calendar time. Three waves at three dates break that.
    cohort_months: dict[str, int] = {}
    sched_path = layer_path("normalized", "tariff_schedule.parquet")
    if sched_path.exists() and "treatment_cohort" in panel.columns:
        sched = pl.read_parquet(sched_path)
        eff = (
            sched.filter(pl.col("record_type") == "ADDITIONAL_DUTY")
            .group_by("action_id")
            .agg(pl.col("effective_date").min())
        )
        cohort_months = {
            r["action_id"]: r["effective_date"].year * 12 + r["effective_date"].month
            for r in eff.iter_rows(named=True)
            if r["action_id"] in set(panel["treatment_cohort"].unique().to_list())
        }

    if len(cohort_months) >= 2:
        for ctrl in [
            "never_treated_products",
            "not_yet_treated",
            "never_treated_products_treated_country_only",
        ]:
            for outcome in [
                "log_landed_unit_value",
                "log_customs_unit_value",
                "log_quantity",
            ]:
                try:
                    fit, spec, coefs, comp = stacked_event_study(
                        panel, outcome, cohort_months, cluster_vars=cluster,
                        window=window, reference=est.reference_event_time
                        if est.reference_event_time <= -3 else -3,
                        control_definition=ctrl,
                    )
                except (ValueError, KeyError) as exc:
                    print(f"rung 4 [{outcome} | {ctrl}] failed: {exc}")
                    continue
                tag = f"{outcome}_{ctrl}"
                _write(
                    coefs.with_columns(
                        pl.lit(outcome).alias("outcome"),
                        pl.lit(ctrl).alias("control_definition"),
                    ),
                    f"stacked_event_study_{tag}",
                    stamp,
                )
                _write(comp, f"stacked_composition_{ctrl}", stamp)
                pt = pretrend_test(coefs, fit)
                pt["design"] = "stacked_multi_wave"
                pt["control_definition"] = ctrl
                diagnostics[f"pretrend_stacked_{tag}"] = pt
                spec_rows.append(spec.to_row() | {"rung": "4_stacked"})
                post = coefs.filter(
                    (pl.col("event_time") >= 0) & (pl.col("std_error") > 0)
                )
                mean_post = float(post["estimate"].mean()) if post.height else float("nan")
                all_rows.append({
                    "term": "stacked_mean_post_effect",
                    "estimate": mean_post,
                    "std_error": float("nan"),
                    "t_stat": float("nan"),
                    "p_value": float("nan"),
                    "ci_low": float("nan"),
                    "ci_high": float("nan"),
                    "estimator": "OLS-HDFE",
                    "n_obs": fit.n_obs,
                    "absorbed_effects": "flow x stack|month x stack",
                    "cluster_vars": "|".join(cluster),
                    "n_clusters_min": min(fit.n_clusters.values()) if fit.n_clusters else None,
                    "outcome": outcome,
                    "outcome_label": f"{outcome} -- stacked, controls={ctrl}",
                    "rung": "4_stacked",
                    # Named so a reader of the results can select the headline
                    # design explicitly. Without it the only way to tell the
                    # three control definitions apart is row order, and the
                    # incidence section of the report was quoting typed-in
                    # constants rather than these numbers at all.
                    "control_definition": ctrl,
                    "n_post_periods": post.height,
                })
                print(
                    f"rung 4 [{outcome:>22} | {ctrl[:28]:28}] n={fit.n_obs:>7,} "
                    f"mean post={mean_post:+.4f} pre-trend {pt['verdict']}"
                )
        # Robustness: the headline design on codes observed in every month.
        #
        # The product-reclassification risk had a mitigation named in the plan --
        # the HS concordance engine -- that the pipeline never called. Without a
        # correlation table this cannot be closed by identifying which codes were
        # renumbered, so it is bounded instead. A code present in every month of
        # the window cannot have been introduced or retired inside it, so this
        # subsample excludes every renumbering candidate. It also excludes codes
        # that merely went untraded for a month, which makes it conservative
        # rather than exact: it is "observed throughout", not "definition stable",
        # and the two are not the same claim.
        #
        # If the headline survives here, code churn is not driving it.
        months = panel["month_date"].n_unique()
        stable = (
            panel.group_by("hs10")
            .agg(pl.col("month_date").n_unique().alias("_m"))
            .filter(pl.col("_m") == months)["hs10"]
            .to_list()
        )
        stable_panel = stable_code_sample(panel, stable, product_col="hs10")
        share_value = (
            stable_panel["customs_value"].sum() / panel["customs_value"].sum()
            if panel["customs_value"].sum()
            else 0.0
        )
        print(
            f"\nrung 4 robustness: {len(stable):,} of {panel['hs10'].n_unique():,} codes are "
            f"observed in all {months} months, {share_value:.1%} of customs value"
        )
        for outcome in ["log_landed_unit_value", "log_customs_unit_value", "log_quantity"]:
            try:
                fit, spec, coefs, comp = stacked_event_study(
                    stable_panel, outcome, cohort_months, cluster_vars=cluster,
                    window=window,
                    reference=est.reference_event_time
                    if est.reference_event_time <= -3 else -3,
                    control_definition="never_treated_products",
                )
            except (ValueError, KeyError) as exc:
                print(f"rung 4 [stable codes | {outcome}] failed: {exc}")
                continue
            pt = pretrend_test(coefs, fit)
            pt["design"] = "stacked_multi_wave"
            pt["control_definition"] = "never_treated_products"
            pt["sample"] = "codes_observed_in_every_month"
            diagnostics[f"pretrend_stable_codes_{outcome}"] = pt
            post = coefs.filter((pl.col("event_time") >= 0) & (pl.col("std_error") > 0))
            mean_post = float(post["estimate"].mean()) if post.height else float("nan")
            all_rows.append({
                "term": "stacked_mean_post_effect",
                "estimate": mean_post,
                "std_error": float("nan"),
                "t_stat": float("nan"),
                "p_value": float("nan"),
                "ci_low": float("nan"),
                "ci_high": float("nan"),
                "estimator": "OLS-HDFE",
                "n_obs": fit.n_obs,
                "absorbed_effects": "flow x stack|month x stack",
                "cluster_vars": "|".join(cluster),
                "n_clusters_min": min(fit.n_clusters.values()) if fit.n_clusters else None,
                "outcome": outcome,
                "outcome_label": f"{outcome} -- stacked, codes observed in every month",
                "rung": "4_stacked_stable_codes",
                "control_definition": "never_treated_products",
                "n_post_periods": post.height,
            })
            print(
                f"rung 4 [{outcome:>22} | stable codes                ] n={fit.n_obs:>7,} "
                f"mean post={mean_post:+.4f} pre-trend {pt['verdict']}"
            )
        stable_meta = {
            "definition": "10-digit codes with an observation in every month of the window",
            "n_codes": len(stable),
            "n_codes_total": int(panel["hs10"].n_unique()),
            "share_of_customs_value": float(share_value),
            "why": (
                "Bounds the product-reclassification risk without a correlation table. A "
                "code present in every month cannot have been introduced or retired "
                "mid-window, so this excludes every renumbering candidate -- and also some "
                "codes that were merely untraded for a month, which makes it conservative "
                "rather than exact. It is 'observed throughout', not 'definition stable'."
            ),
        }
    else:
        print("rung 4: fewer than two treatment cohorts in the panel; stacked design skipped")

    # ---------------------------------------------------------------- #
    # Rung 5: PPML on trade flows in levels (retains zeros)
    # ---------------------------------------------------------------- #
    # Primary treatment is log(1 + additional duty): it isolates the policy
    # variation and is defined for every row. log(1 + total duty) is run as a
    # robustness variant on the subsample where a single ad valorem MFN baseline
    # exists, and the two are reported side by side rather than merged.
    for treat_var, sample_label in [
        ("log1p_additional_tariff", "full sample"),
        ("log1p_total_tariff", "subsample with an ad valorem MFN baseline"),
    ]:
        sub = panel if treat_var == "log1p_additional_tariff" else panel.filter(
            pl.col("baseline_mfn_available")
        )
        for outcome in ["customs_value", "quantity"]:
            fit, spec = ppml_trade_flow(
                sub,
                outcome=outcome,
                treatment=treat_var,
                fixed_effects=fe_flow_time,
                cluster_vars=cluster,
            )
            rows = fit.to_rows()
            for r in rows:
                r["outcome"] = outcome
                r["outcome_label"] = f"{outcome} (levels, PPML; {sample_label})"
                r["rung"] = "5_ppml"
            all_rows.extend(rows)
            spec_rows.append(
                spec.to_row() | {"rung": "5_ppml", "sample": sample_label}
            )
            b = fit.params[treat_var]
            lo, hi = fit.conf_int(treat_var)
            print(
                f"rung 5 [{outcome:>15} ~ {treat_var:>24}] elasticity={b:+.4f} "
                f"95% CI [{lo:+.4f}, {hi:+.4f}] n={fit.n_obs:,} converged={fit.converged}"
            )
            if fit.notes:
                for nte in fit.notes:
                    print(f"           note: {nte}")

    # ---------------------------------------------------------------- #
    # Rung 6: heterogeneity by pre-treatment dependence on the treated country
    # ---------------------------------------------------------------- #
    med = panel["pretreatment_treated_country_share"].median()
    het = panel.with_columns(
        (pl.col("pretreatment_treated_country_share") > med).alias("high_dependence")
    )
    for grp, label in [(True, "high_pretreatment_dependence"), (False, "low_pretreatment_dependence")]:
        sub = het.filter(pl.col("high_dependence") == grp)
        try:
            fit, _ = two_way_fe_regression(
                sub, "log_quantity", "additional_tariff_rate",
                fixed_effects=fe_flow_time, cluster_vars=cluster,
            )
            rows = fit.to_rows()
            for r in rows:
                r["outcome"] = "log_quantity"
                r["outcome_label"] = f"log quantity -- {label} (split at median {med:.3f})"
                r["rung"] = "6_heterogeneity"
            all_rows.extend(rows)
            print(f"rung 6 [{label:>28}] beta={fit.params['additional_tariff_rate']:+.4f}")
        except Exception as exc:  # noqa: BLE001
            print(f"rung 6 [{label}] failed: {exc}")

    # ---------------------------------------------------------------- #
    # Incidence accounting: is the landed-cost rise mechanical, and did the
    # exporter cut its border price?
    # ---------------------------------------------------------------- #
    # The duty-inclusive landed measure contains the duty by construction, so
    # part of its rise is arithmetic rather than behaviour. What is NOT
    # mechanical is the customs (tariff-exclusive) unit value: if the exporter
    # absorbed part of the tariff, that series falls. Reporting the mechanical
    # benchmark beside both estimates is what separates the two.
    treated_flows = panel.filter(
        pl.col("is_treated_country") & pl.col("treated") & (pl.col("customs_value") > 0)
    )
    incidence: dict = {}
    if treated_flows.height:
        tau = float(
            (treated_flows["additional_tariff_rate"] * treated_flows["customs_value"]).sum()
            / treated_flows["customs_value"].sum()
        )
        incidence = {
            "value_weighted_additional_duty_in_force": tau,
            "mechanical_log1p_tau_if_no_absorption": float(np.log1p(tau)),
            "interpretation": (
                "log(1+tau) is what the duty-inclusive landed unit value would rise by if the "
                "exporter absorbed none of the tariff. The customs unit value response is the "
                "behavioural quantity: it falls only if the exporter cuts its border price. "
                "The landed measure contains the duty by construction, so its rise is partly "
                "arithmetic and is not independent evidence on its own."
            ),
        }
        print(
            f"\nincidence accounting: value-weighted duty in force tau={tau:.4f}; "
            f"mechanical log(1+tau)={np.log1p(tau):.4f} if the exporter absorbs nothing"
        )

    # ---------------------------------------------------------------- #
    # Control-group contamination (SUTVA) diagnostic
    # ---------------------------------------------------------------- #
    # Alternative suppliers of a treated product are not untreated bystanders:
    # the policy pushes demand toward them. Using them as controls violates the
    # no-interference assumption and biases the treatment coefficient away from
    # zero. The diagnostic compares two control groups:
    #
    #   (a) all untreated flows, including third-country flows of treated
    #       products -- the conventional choice, contaminated by diversion;
    #   (b) treated-country flows of never-treated products only -- immune to
    #       diversion spillover, at the cost of a weaker common-shock argument.
    #
    # A gap between them is evidence of spillover, not noise.
    sutva_rows: list[dict] = []
    sutva_diagnostic: dict = {}
    contaminated = panel
    clean = panel.filter(
        pl.col("is_treated_country")  # only treated-country flows
    )
    for label, sub in [
        ("all_untreated_flows_incl_third_country", contaminated),
        ("treated_country_flows_only", clean),
    ]:
        for outcome in ["log_quantity", "log_customs_unit_value"]:
            try:
                fit, _ = two_way_fe_regression(
                    sub, outcome, "additional_tariff_rate",
                    fixed_effects=fe_flow_time, cluster_vars=cluster,
                )
                lo, hi = fit.conf_int("additional_tariff_rate")
                sutva_rows.append(
                    {
                        "control_group": label,
                        "outcome": outcome,
                        "estimate": fit.params["additional_tariff_rate"],
                        "std_error": fit.std_errors["additional_tariff_rate"],
                        "ci_low": lo,
                        "ci_high": hi,
                        "n_obs": fit.n_obs,
                    }
                )
                print(f"SUTVA [{label:>38} | {outcome:>24}] beta="
                      f"{fit.params['additional_tariff_rate']:+.4f}")
            except Exception as exc:  # noqa: BLE001
                print(f"SUTVA [{label} | {outcome}] failed: {exc}")
    if sutva_rows:
        _write(pl.DataFrame(sutva_rows), "sutva_control_group_diagnostic", stamp)
        sutva_diagnostic = {
            "description": (
                "Comparison of treatment estimates under a diversion-contaminated control "
                "group versus a control group restricted to treated-country flows of "
                "never-treated products."
            ),
            "rows": sutva_rows,
            "interpretation": (
                "A gap indicates that third-country suppliers of treated products respond to "
                "the policy, so they are not valid controls. In trade settings this is the "
                "rule, not the exception."
            ),
        }

    # ---------------------------------------------------------------- #
    # Identification checks
    # ---------------------------------------------------------------- #
    checks: list[dict] = []

    # (a) Placebo treatment date: pretend treatment happened 12 months early,
    #     estimated on pre-period data only so the real shock cannot leak in.
    real_first = panel["first_treated_month_index"].min()
    placebo = panel.filter(
        pl.col("month_index") < (real_first if real_first is not None else 0)
    ).with_columns(
        (pl.col("month_index") - (pl.col("first_treated_month_index") - 12)).alias("event_time")
    )
    if placebo.height > 500:
        # Run on every outcome, and say which. It used to run on `log_quantity`
        # alone and record no outcome at all, so a reader met a placebo reporting
        # a significant effect with no way to tell whether it threatened the
        # incidence claim -- which rests on the two price outcomes -- or the
        # quantity result, which already carries a qualified reading. Testing
        # only the outcome that fails its own pre-trend test, and not the two
        # carrying the conclusion, is the wrong way round.
        for outcome in ["log_customs_unit_value", "log_landed_unit_value", "log_quantity"]:
            try:
                fit, _, coefs = event_study(
                    placebo, outcome,
                    fixed_effects=fe_flow_time, cluster_vars=cluster,
                    window=(-6, 5), reference=-1,
                )
                post = coefs.filter((pl.col("event_time") >= 0) & (pl.col("std_error") > 0))
                sig = bool((post["p_value"] < 0.05).any()) if post.height else None
                checks.append(
                    {
                        "check": "placebo_treatment_date_minus_12m",
                        "outcome": outcome,
                        "description": (
                            "treatment date moved 12 months earlier, pre-period sample only"
                        ),
                        "n_obs": fit.n_obs,
                        "max_abs_post_coef": (
                            float(np.max(np.abs(post["estimate"].to_numpy())))
                            if post.height
                            else None
                        ),
                        "any_post_significant_5pct": sig,
                        "status": "FAIL" if sig else "PASS",
                        "interpretation": (
                            "a significant 'effect' here means the design picks up differential "
                            "trends rather than the tariff, for this outcome"
                        ),
                    }
                )
                _write(coefs.with_columns(pl.lit(outcome).alias("outcome")),
                       f"placebo_event_study_date_{outcome}", stamp)
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    {"check": "placebo_treatment_date_minus_12m",
                     "outcome": outcome, "error": str(exc)}
                )
    else:
        checks.append(
            {"check": "placebo_treatment_date_minus_12m", "status": "SKIPPED",
             "reason": f"only {placebo.height} pre-period observations"}
        )

    # (b) Placebo product group: assign treatment to control products only.
    ctrl = panel.filter(~pl.col("ever_treated_product"))
    if ctrl.height > 500:
        codes = sorted(ctrl["hs6"].unique().to_list())
        fake = set(codes[: len(codes) // 2])
        first_idx = int(panel.filter(pl.col("ever_treated_product"))["first_treated_month_index"].min())
        cp = ctrl.with_columns(
            pl.col("hs6").is_in(list(fake)).alias("_fake_product"),
        ).with_columns(
            (pl.col("month_index") - first_idx).alias("event_time"),
            (pl.col("_fake_product") & pl.col("is_treated_country")).alias("_fake_treat"),
        )
        try:
            fit, _, coefs = event_study(
                cp, "log_quantity", fixed_effects=fe_flow_time, cluster_vars=cluster,
                window=(-6, 5), reference=-1, treat_col="_fake_treat",
            )
            post = coefs.filter((pl.col("event_time") >= 0) & (pl.col("std_error") > 0))
            checks.append(
                {
                    "check": "placebo_product_group",
                    "description": "half the never-treated products labelled treated at the real date",
                    "n_obs": fit.n_obs,
                    "max_abs_post_coef": float(np.max(np.abs(post["estimate"].to_numpy()))) if post.height else None,
                    "any_post_significant_5pct": bool((post["p_value"] < 0.05).any()) if post.height else None,
                }
            )
            _write(coefs, "placebo_event_study_product", stamp)
        except Exception as exc:  # noqa: BLE001
            checks.append({"check": "placebo_product_group", "error": str(exc)})

    # (c) Announcement date vs effective date.
    for datecol, label in [("additional_tariff_rate", "effective_date_treatment")]:
        checks.append(
            {
                "check": "announcement_vs_effective",
                "status": "PARTIAL",
                "note": (
                    "the tariff schedule stores announcement and effective dates separately and "
                    "the event study uses the effective date; an announcement-dated variant "
                    "requires re-deriving event time from announcement_date and is listed as a "
                    "remaining milestone"
                ),
                "treatment_used": datecol,
                "label": label,
            }
        )

    # (d) Leave-one-chapter-out stability.
    loo = []
    for ch in sorted(panel["hs2_chapter"].unique().to_list()):
        sub = panel.filter(pl.col("hs2_chapter") != ch)
        if sub["hs6"].n_unique() < 10:
            continue
        try:
            fit, _ = two_way_fe_regression(
                sub, "log_quantity", "additional_tariff_rate",
                fixed_effects=fe_flow_time, cluster_vars=cluster,
            )
            loo.append({"dropped_chapter": ch, "estimate": fit.params["additional_tariff_rate"],
                        "std_error": fit.std_errors["additional_tariff_rate"], "n_obs": fit.n_obs})
        except Exception:  # noqa: BLE001, S112
            continue
    if loo:
        loo_df = pl.DataFrame(loo)
        _write(loo_df, "leave_one_chapter_out", stamp)
        spread = float(loo_df["estimate"].max() - loo_df["estimate"].min())
        checks.append(
            {"check": "leave_one_chapter_out", "n_variants": len(loo),
             "estimate_spread": spread,
             "min": float(loo_df["estimate"].min()), "max": float(loo_df["estimate"].max())}
        )
        print(f"leave-one-chapter-out: {len(loo)} variants, estimate spread {spread:.4f}")

    # (e) Leave-one-country-out stability.
    looc = []
    for c in sorted(panel["country_code"].unique().to_list()):
        if c == cfg.sample.treated_country_code:
            continue
        sub = panel.filter(pl.col("country_code") != c)
        try:
            fit, _ = two_way_fe_regression(
                sub, "log_quantity", "additional_tariff_rate",
                fixed_effects=fe_flow_time, cluster_vars=cluster,
            )
            looc.append({"dropped_country": c, "estimate": fit.params["additional_tariff_rate"],
                         "std_error": fit.std_errors["additional_tariff_rate"], "n_obs": fit.n_obs})
        except Exception:  # noqa: BLE001, S112
            continue
    if looc:
        _write(pl.DataFrame(looc), "leave_one_country_out", stamp)
        checks.append({"check": "leave_one_country_out", "n_variants": len(looc)})

    # ---------------------------------------------------------------- #
    _write(pl.DataFrame(all_rows), "incidence_estimates", stamp)
    _write(pl.DataFrame(spec_rows), "specification_register", stamp)
    (layer_path("results", "identification_checks.json")).write_text(
        json.dumps(
            {"run": stamp.to_dict(), "pretrend_tests": diagnostics,
             "stable_code_sample": stable_meta,
             "incidence_accounting": incidence,
             "sutva_control_group": sutva_diagnostic, "checks": checks},
            indent=2, default=str,
        )
        + "\n"
    )
    stamp.write(layer_path("results", "incidence.runstamp.json"))
    print(f"\nwrote results to data/results (run_id={stamp.run_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
