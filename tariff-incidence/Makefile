SHELL := /bin/bash
PY := .venv/bin/python
UV := $(shell command -v uv 2>/dev/null || echo "$$HOME/.local/bin/uv")

.DEFAULT_GOAL := help
.PHONY: help setup download-sample build-tariff-schedule build-trade-panel validate-data \
        descriptive replicate estimate-incidence estimate-diversion build-io-exposure \
        structural test lint typecheck reproduce-sample report dashboard clean check \
        build-io-exposure-detail estimate-propagation-detail check-consistency

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-24s\033[0m %s\n",$$1,$$2}'

setup: ## Create the virtualenv and install dependencies (needs uv)
	@command -v uv >/dev/null 2>&1 || python3 -m pip install --user uv
	$(UV) venv --python 3.12
	$(UV) pip install -e ".[dev,dash]"
	@echo "done. If CENSUS_API_KEY is unset the pipeline runs in labelled synthetic mode."
	@echo "Free key: https://api.census.gov/data/key_signup.html"

download-sample: ## Fetch official source documents into data/raw (cached)
	$(PY) scripts/download_sources.py

build-tariff-schedule: ## Parse Section 301 annexes into the tariff schedule
	$(PY) scripts/build_tariff_schedule.py

build-trade-panel: ## Build the product x country x month analytical panel
	$(PY) scripts/build_trade_panel.py

validate-data: ## Run the data-quality battery
	$(PY) scripts/validate_data.py

descriptive: ## Descriptive trade analysis
	$(PY) scripts/descriptive.py

replicate: ## Run the replication benchmark
	$(PY) scripts/replicate.py

estimate-incidence: ## Model ladder, event studies, PPML, placebos
	$(PY) scripts/estimate_incidence.py

estimate-diversion: ## Trade-diversion decomposition
	$(PY) scripts/estimate_diversion.py

build-io-exposure: ## Map tariff exposure into industries via BEA input-output
	$(PY) scripts/build_io_exposure.py

estimate-propagation: ## Test whether exposure shows up in domestic producer prices
	$(PY) scripts/estimate_propagation.py

check-consistency: ## Do the result tables agree with each other?
	$(PY) scripts/check_consistency.py --fail-on-error

structural: ## Armington sourcing counterfactual (one-tier, no domestic nest, no welfare)
	$(PY) scripts/structural_counterfactual.py

test: ## Run the test suite
	$(PY) -m pytest -q

lint: ## ruff
	$(PY) -m ruff check src tests scripts

typecheck: ## mypy on core interfaces
	$(PY) -m mypy

check: lint typecheck test ## Lint, typecheck and test

report: ## Regenerate every report from result tables
	$(PY) scripts/generate_reports.py

dashboard: ## Launch the Streamlit dashboard
	.venv/bin/streamlit run dashboard/app.py

reproduce-sample: build-tariff-schedule build-trade-panel validate-data descriptive \
                  replicate estimate-incidence estimate-diversion build-io-exposure \
                  estimate-propagation structural check-consistency report ## Full end-to-end small run
	@echo ""
	@echo "End-to-end run complete. Reports are in reports/."
	@echo "Provenance is recorded in each report's banner."

clean: ## Remove derived data (keeps data/raw and manifests)
	rm -rf data/staged/* data/normalized/* data/analytical/* data/results/*
	@echo "cleaned derived layers; data/raw and data/manifests kept"

build-io-exposure-detail: ## Industry exposure at BEA detail level (~400 industries)
	$(PY) scripts/build_io_exposure.py --level detail

estimate-propagation-detail: ## Propagation test with detail-level clusters
	$(PY) scripts/estimate_propagation.py --level detail
