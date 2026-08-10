RUNTIME_PYTHON ?= python3.12
VENV := .venv
PYTHON := $(VENV)/bin/python
CLI := $(PYTHON) -m macro_nowcast.cli

.PHONY: setup download-sample build-vintages validate-asof backtest test reproduce-sample reproduce-multitarget index-empsit-clocks acquire-dol-claims acquire-fed-g17 acquire-treasury-rates acquire-bea-nipa-levels audit-bea-nipa-levels acquire-census-retail acquire-census-housing audit-agency-vintages ingest-agency-vintages reproduce-official-pilot policy-brief report dashboard lint clean-generated

setup:
	$(RUNTIME_PYTHON) scripts/check_python.py
	$(RUNTIME_PYTHON) -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e '.[dev]'

download-sample:
	$(CLI) prepare-sample --config config/sample.toml

build-vintages:
	$(CLI) build-vintages --config config/sample.toml

validate-asof:
	$(CLI) validate-asof --config config/sample.toml

backtest:
	$(CLI) backtest --config config/sample.toml

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

reproduce-sample:
	$(CLI) reproduce-sample --config config/sample.toml

reproduce-multitarget:
	$(CLI) reproduce-multitarget --config config/targets.toml

index-empsit-clocks:
	$(CLI) index-empsit-clocks --source-dir data/raw/agency_vintages/bls-empsit-clock-txt --release-index data/raw/agency_vintages/empsit-release-index.json

acquire-dol-claims:
	$(CLI) acquire-dol-claims --output-dir data/raw/agency_vintages/dol-ui-claims --start-year 2002

acquire-fed-g17:
	$(CLI) acquire-fed-g17 --output-dir data/raw/agency_vintages/fed-g17 --start-year 1997

acquire-treasury-rates:
	$(CLI) acquire-treasury-rates --output-dir data/raw/agency_vintages/treasury-yield-curve --start-year 2002

acquire-bea-nipa-levels:
	$(CLI) acquire-bea-nipa-levels --output-dir data/raw/agency_vintages/bea-nipa-levels --clock-evidence data/raw/agency_vintages/bea-gdp-news/clock-evidence.json --published-growth data/raw/agency_vintages/gdp-gdi-vintage-history.xlsx

audit-bea-nipa-levels:
	$(CLI) audit-bea-nipa-levels --source-dir data/raw/agency_vintages/bea-nipa-levels --clock-evidence data/raw/agency_vintages/bea-gdp-news/clock-evidence.json --published-growth data/raw/agency_vintages/gdp-gdi-vintage-history.xlsx

acquire-census-retail:
	$(CLI) acquire-census-retail --output-dir data/raw/agency_vintages/census-marts --start-year 2003

acquire-census-housing:
	$(CLI) acquire-census-housing --output-dir data/raw/agency_vintages/census-nrc --start-year 2003

audit-agency-vintages:
	$(CLI) audit-agency-vintages --raw-dir data/raw/agency_vintages --output data/generated/agency_vintages/audit_manifest.json

ingest-agency-vintages:
	$(CLI) ingest-agency-vintages --raw-dir data/raw/agency_vintages --output-dir data/generated/official_vintages --overwrite

reproduce-official-pilot:
	$(CLI) reproduce-official-pilot --source-dir data/generated/official_vintages --output-dir data/generated/official_pilot --overwrite

policy-brief:
	$(CLI) policy-brief --config config/sample.toml

report:
	$(CLI) report --config config/sample.toml

dashboard:
	$(PYTHON) -m streamlit run scripts/dashboard_entry.py -- --config config/sample.toml

clean-generated:
	$(CLI) clean-generated --config config/sample.toml
