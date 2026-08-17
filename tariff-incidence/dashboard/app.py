"""Lightweight Streamlit dashboard.

    make dashboard

Every displayed estimate carries its sample, outcome, treatment definition,
aggregation level, time period, weighting and specification. A number without
that context is not shown.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import polars as pl  # noqa: E402
import streamlit as st  # noqa: E402

from tariff_incidence.manifest import list_manifests  # noqa: E402
from tariff_incidence.paths import layer_path  # noqa: E402

RESULTS = ROOT / "data" / "results"

st.set_page_config(page_title="Tariff Incidence", layout="wide")


def read(name: str) -> pl.DataFrame | None:
    p = RESULTS / f"{name}.parquet"
    return pl.read_parquet(p) if p.exists() else None


def read_json(name: str) -> dict | None:
    p = RESULTS / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


panel_stamp_path = layer_path("analytical", "trade_panel.runstamp.json")
stamp = json.loads(panel_stamp_path.read_text()) if panel_stamp_path.exists() else {}
provenance = stamp.get("data_provenance", "UNKNOWN")

st.title("Tariff Incidence, Supply-Chain Reallocation, and Domestic Propagation")

if provenance != "OFFICIAL":
    st.error(
        f"**DATA PROVENANCE: {provenance}** — trade flows come from the documented synthetic "
        "generator. Every estimate below measures whether the estimation code behaves as "
        "designed. Nothing here describes U.S. trade. Set `CENSUS_API_KEY` and rebuild to "
        "produce official results.",
        icon="🚫",
    )
else:
    st.success("**DATA PROVENANCE: OFFICIAL** — all inputs trace to official sources.", icon="✅")

c1, c2, c3, c4 = st.columns(4)
c1.metric("run id", stamp.get("run_id", "—")[:18])
c2.metric("git commit", stamp.get("git_commit", "—"))
c3.metric("data period", f"{stamp.get('data_period_start')} → {stamp.get('data_period_end')}")
c4.metric("config", stamp.get("config_name", "—"))

tabs = st.tabs(
    [
        "Tariff timeline",
        "Product & sourcing",
        "Incidence estimates",
        "Diversion",
        "Industry exposure",
        "Structural",
        "Data quality",
        "Pipeline status",
    ]
)

# ---------------------------------------------------------------- tariff
with tabs[0]:
    st.header("Section 301 tariff timeline")
    sched_p = layer_path("normalized", "tariff_schedule.parquet")
    if sched_p.exists():
        sched = pl.read_parquet(sched_p)
        summary = (
            sched.group_by(
                ["action_id", "record_type", "announcement_date", "effective_date",
                 "ad_valorem_rate", "source_citation"]
            )
            .agg(pl.len().alias("n_lines"), pl.col("partial_line").sum().alias("n_partial"))
            .sort("effective_date")
        )
        st.dataframe(summary.to_pandas(), width="stretch")
        st.caption(
            "Announcement and effective dates are distinct facts. The List 3 increase was "
            "announced for 2019-01-01, postponed twice, and took effect 2019-05-10."
        )
        parse = layer_path("normalized", "tariff_schedule_parse_report.json")
        if parse.exists():
            rep = json.loads(parse.read_text())
            st.subheader("Parse validation against each notice's own stated count")
            st.dataframe(
                pl.DataFrame(
                    [
                        {
                            "document": p["document_number"],
                            "heading": p["chapter99_heading"],
                            "parsed": p["parsed_line_count"],
                            "stated in notice": p["stated_line_count"],
                            "match": p["count_matches_notice"],
                        }
                        for p in rep["parses"]
                    ],
                    strict=False,
                ).to_pandas(),
                width="stretch",
            )
    else:
        st.info("Run `make build-tariff-schedule`.")

# ------------------------------------------------------- product/sourcing
with tabs[1]:
    st.header("Product search and sourcing")
    ppath = layer_path("analytical", "trade_panel.parquet")
    if ppath.exists():
        panel = pl.read_parquet(ppath)
        # The panel's unit is the 10-digit line. Selecting an HS6 and charting it
        # directly would silently pool several statistical numbers whose tariff
        # treatment, units of quantity and unit values all differ -- and a unit
        # value pooled across unlike quantity units is not a quantity at all. So
        # the HS6 box narrows the choice and the 10-digit box makes it.
        products = sorted(panel["hs6"].unique().to_list())
        sel6 = st.selectbox("HS6 heading", products)
        within = panel.filter(pl.col("hs6") == sel6)
        ranked = (
            within.group_by("hs10")
            .agg(pl.col("customs_value").sum().alias("v"))
            .sort("v", descending=True)
        )
        lines = ranked["hs10"].to_list()
        if len(lines) > 1:
            st.caption(
                f"{len(lines)} ten-digit lines sit under {sel6}; they are shown one at a "
                "time rather than pooled, because their tariff treatment and units of "
                "quantity need not agree."
            )
        sel = st.selectbox("10-digit line (largest by customs value first)", lines)
        sub = panel.filter(pl.col("hs10") == sel)
        meta = sub.row(0, named=True)
        # `tariff_status` is the engine's match status for one line-country-month,
        # not a property of the product: it reads OK exactly on the observations
        # that are actually dutied and NO_MATCH everywhere else, so showing the
        # first row's value would report whichever row happened to sort first.
        # The product-level facts are when the duty started and how high it went.
        treated_obs = sub.filter(pl.col("treated"))
        peak = treated_obs["additional_tariff_rate"].max() if treated_obs.height else None
        first_month = treated_obs["month_date"].min() if treated_obs.height else None
        m1, m2, m3 = st.columns(3)
        m1.metric("ever treated", "yes" if meta["ever_treated_product"] else "no")
        m2.metric("pre-treatment China share", f"{meta['pretreatment_treated_country_share']:.1%}")
        m3.metric(
            "peak additional rate",
            f"{peak:.1%}" if peak is not None else "—",
            help=(
                f"first dutied month {first_month}" if first_month is not None
                else "no dutied observation in this window"
            ),
        )

        st.subheader("Customs value by partner")
        wide = sub.pivot(on="country_code", index="month_date", values="customs_value")
        st.line_chart(wide.to_pandas().set_index("month_date"))

        st.subheader("Customs vs duty-inclusive unit value (China)")
        cn = sub.filter(pl.col("is_treated_country")).select(
            ["month_date", "customs_unit_value", "landed_unit_value_duty_inclusive"]
        )
        st.line_chart(cn.to_pandas().set_index("month_date"))
        st.caption(
            "A unit value is value divided by quantity over a heterogeneous bundle. It is not "
            "a transaction price."
        )

        st.subheader("Treated-country share and supplier concentration")
        conc = sub.select(
            ["month_date", "treated_country_share", "supplier_hhi_in_sample"]
        ).unique().sort("month_date")
        st.line_chart(conc.to_pandas().set_index("month_date"))
    else:
        st.info("Run `make build-trade-panel`.")

# ------------------------------------------------------------- incidence
with tabs[2]:
    st.header("Incidence estimates")
    est = read("incidence_estimates")
    specs = read("specification_register")
    if est is not None:
        st.dataframe(
            est.select(
                ["rung", "outcome_label", "term", "estimate", "std_error", "ci_low", "ci_high",
                 "p_value", "n_obs", "absorbed_effects", "cluster_vars", "data_provenance"]
            ).to_pandas(),
            width="stretch",
        )
    for outcome in ["log_customs_unit_value", "log_landed_unit_value", "log_quantity"]:
        for ref in [1, 3]:
            ev = read(f"event_study_{outcome}_ref{ref}")
            if ev is None:
                continue
            with st.expander(f"Event study — {outcome} (reference −{ref})"):
                d = ev.filter(pl.col("event_time").is_not_null()).sort("event_time")
                st.line_chart(
                    d.select(["event_time", "estimate", "ci_low", "ci_high"])
                    .to_pandas()
                    .set_index("event_time")
                )
                st.dataframe(d.to_pandas(), width="stretch")

    ident = read_json("identification_checks")
    if ident:
        st.subheader("Pre-trend tests")
        st.dataframe(
            pl.DataFrame(
                [{"test": k, **{a: b for a, b in v.items() if a != "caveat"}}
                 for k, v in ident.get("pretrend_tests", {}).items()],
                strict=False,
            ).to_pandas(),
            width="stretch",
        )
        st.subheader("Placebo and stability checks")
        st.dataframe(pl.DataFrame(ident.get("checks", []), strict=False).to_pandas(),
                     width="stretch")
    sut = read("sutva_control_group_diagnostic")
    if sut is not None:
        st.subheader("Control-group contamination diagnostic")
        st.dataframe(sut.to_pandas(), width="stretch")
        st.caption(
            "Third-country suppliers of a treated product are not untreated bystanders. A gap "
            "between the two control groups is evidence of diversion spillover."
        )
    if specs is not None:
        with st.expander("Specification register"):
            st.dataframe(specs.to_pandas(), width="stretch")

# ------------------------------------------------------------- diversion
with tabs[3]:
    st.header("Trade diversion")
    tot = read("diversion_totals")
    adj = read("diversion_counterfactual_adjusted")
    gains = read("diversion_country_gains")
    if tot is not None:
        t = tot.row(0, named=True)
        a, b, c = st.columns(3)
        a.metric("treated-country change", f"{t['treated_total']:,.0f}")
        b.metric("alternative-source change", f"{t['alternative_total']:,.0f}")
        c.metric("net change", f"{t['total_change']:,.0f}")
        st.caption("Contraction and expansion are reported separately and never netted.")
    if adj is not None:
        st.subheader("Counterfactual-adjusted (net of never-treated product growth)")
        st.dataframe(adj.to_pandas(), width="stretch")
        st.info(
            "The raw pre/post replacement ratio credits ordinary trade growth to the tariff. "
            "Read the adjusted figures."
        )
    if gains is not None:
        st.subheader("Partner-country detail")
        st.dataframe(gains.to_pandas(), width="stretch")
    st.warning(
        "A third-country increase in customs data is consistent with relocated production, "
        "rerouting of treated-origin goods, and origin misdeclaration. Customs statistics "
        "cannot separate these."
    )

# ------------------------------------------------------------- exposure
with tabs[4]:
    st.header("Industry exposure")
    has_detail = read("industry_tariff_exposure_detail") is not None
    level = "summary"
    if has_detail:
        level = st.radio(
            "BEA industry level",
            ["summary", "detail"],
            horizontal=True,
            help="Detail (~400 industries) is published for benchmark years only; 2017 is "
                 "the pre-treatment year, so the weights stay pre-determined either way.",
        )
    sfx = "" if level == "summary" else "_detail"
    expo = read(f"industry_tariff_exposure{sfx}")
    summ = read(f"industry_exposure_summary{sfx}")
    if expo is not None:
        if summ is not None:
            st.dataframe(summ.to_pandas(), width="stretch")
        st.subheader("Protection vs imported-input cost, by industry")
        st.dataframe(
            expo.select(
                ["industry_code", "industry_name", "output_protection_exposure",
                 "imported_input_cost_exposure", "downstream_total_requirements_exposure",
                 "exposure_class", "concordance_status"]
            ).to_pandas(),
            width="stretch",
        )
        st.warning(
            "The two channels are never netted, and they are not comparable as levels. "
            "Protection is the statutory rate on one commodity; input cost is averaged over "
            "the whole purchase basket, most of which carries no tariff, so it is "
            "mechanically smaller. Only the separately estimated coefficients say which "
            "channel bites harder."
        )
        q = read_json(f"io_exposure_quality{sfx}")
        if q:
            st.caption(f"Concordance status: {q.get('concordance_config_status')} — "
                       f"{q['concordance']['aggregation_loss']}")
            dm = q.get("naics_to_bea_detail") or {}
            if dm.get("n_naics_unmapped"):
                # Two distinct reasons a code reaches no industry, and calling
                # them both "retired" would be wrong: 91xxxx/93xxxx are Census
                # pseudo-industries for scrap and used goods, which have no
                # producing industry at all and which BEA also carries as
                # special rows with no NAICS counterpart.
                unmapped = list(dm["unmapped_naics"])
                pseudo = [c for c in unmapped if c[:2] in {"91", "93"}]
                retired = [c for c in unmapped if c not in pseudo]
                parts = []
                if retired:
                    parts.append(
                        f"{', '.join(retired)} — a NAICS code the 2012-to-2017 revision "
                        "retired on a line that no longer exists in the revised file, so "
                        "there is no successor to read off"
                    )
                if pseudo:
                    parts.append(
                        f"{', '.join(pseudo)} — Census pseudo-industries for scrap and used "
                        "or second-hand goods, which have no producing industry at all"
                    )
                st.caption(
                    f"{dm['n_naics_unmapped']} NAICS codes reach no BEA detail industry: "
                    + "; ".join(parts)
                    + f". {dm.get('n_naics_ambiguous', 0)} are claimed by two industries at "
                    "equal depth and are left unassigned rather than broken arbitrarily."
                )
    else:
        st.info(f"Run `make build-io-exposure{'-detail' if level == 'detail' else ''}`.")

# ------------------------------------------------------------- structural
with tabs[5]:
    st.header("Structural counterfactuals")
    struct = read("structural_sourcing_counterfactual")
    ledger = read("structural_parameter_ledger")
    ssum = read_json("structural_summary")
    if struct is not None and ssum:
        st.info(ssum["scope"])
        st.caption(ssum["premise"])
        routes = ssum["sigma_routes"]
        c1, c2, c3 = st.columns(3)
        c1.metric("sigma fitted to sourcing shares",
                  f"{routes['fitted_to_observed_reallocation']:.2f}"
                  if routes.get("fitted_to_observed_reallocation") else "—")
        c2.metric("sigma inverted from PPML quantity",
                  f"{routes['inverted_from_ppml_quantity_response']:.2f}"
                  if routes.get("inverted_from_ppml_quantity_response") else "—")
        c3.metric("observed treated share, post",
                  f"{ssum['observed_treated_share_post']:.3f}")
        st.subheader("Counterfactual sourcing and import bundle cost")
        st.dataframe(struct.select(
            ["sigma", "sigma_source", "parameter_type", "treated_share_pre",
             "treated_share_model", "treated_share_observed",
             "log_import_bundle_cost_change"]
        ).to_pandas(), width="stretch")
        st.warning(
            "Every `treated_share_model` figure is MODEL-IMPLIED, not observed. The import "
            "bundle cost change is a component of a welfare calculation, not a welfare "
            "number: this model has no domestic nest, no revenue recycling and no labour "
            "market, and none is produced anywhere in the project."
        )
        if ledger is not None:
            st.subheader("Data moments, estimates, calibrated parameters, model outputs")
            st.dataframe(ledger.to_pandas(), width="stretch")
    else:
        st.info("Run `make structural`.")

# ---------------------------------------------------------------- quality
with tabs[6]:
    st.header("Data quality")
    dq = read("data_quality_report")
    if dq is not None:
        st.dataframe(dq.to_pandas(), width="stretch")
        st.caption("A check that could not run is reported SKIPPED, never PASS.")
    else:
        st.info("Run `make validate-data`.")

# ---------------------------------------------------------------- status
with tabs[7]:
    st.header("Pipeline status and data freshness")
    mans = list_manifests()
    if mans:
        st.dataframe(
            pl.DataFrame(
                [
                    {
                        "dataset": m.dataset_id,
                        "layer": m.layer,
                        "rows": m.row_count,
                        "provenance": m.data_provenance,
                        "retrieved": m.retrieval_timestamp_utc[:19],
                        "vintage": m.source_release_or_vintage[:60],
                        "checksum": m.checksum_sha256[:12],
                    }
                    for m in mans
                ]
            ).to_pandas(),
            width="stretch",
        )
        st.subheader("Known limitations recorded on each dataset")
        for m in mans:
            if m.known_limitations:
                with st.expander(m.dataset_id):
                    for lim in m.known_limitations:
                        st.markdown(f"- {lim}")
    else:
        st.info("No manifests yet. Run `make reproduce-sample`.")
