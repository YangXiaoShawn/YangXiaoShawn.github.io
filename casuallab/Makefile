BASE_PYTHON ?= python3
PYTHON ?= .venv/bin/python
SAMPLE_CONFIG ?= configs/sample.yaml
NYC_SAMPLE_CONFIG ?= configs/nyc_sample.yaml
NYC_FULL_CONFIG ?= configs/full.yaml
SIM_CONFIG ?= configs/simulation.yaml
BENCHMARK_CONFIG ?= configs/benchmark.yaml
POLICY_CONFIG ?= configs/policy.yaml

.PHONY: setup download-sample validate-nyc-sample validate-nyc-full nyc-simulation-anchor nyc-weather nyc-events nyc-income nyc-benchmark nyc-graph-benchmark equilibrium-benchmark build-panel simulate benchmark interference-benchmark test lint reproduce-sample report dashboard

setup:
	test -x .venv/bin/python || $(BASE_PYTHON) -m venv .venv
	.venv/bin/python -m pip install -c constraints.txt -e ".[dev,dashboard]"

download-sample:
	$(PYTHON) -m casuallab download-sample --config $(SAMPLE_CONFIG)

validate-nyc-sample:
	$(PYTHON) -m casuallab build-panel --config $(NYC_SAMPLE_CONFIG) --refresh

validate-nyc-full:
	$(PYTHON) -m casuallab validate-nyc-full --config $(NYC_FULL_CONFIG) --allow-full-download

nyc-simulation-anchor:
	$(PYTHON) -m casuallab nyc-simulation-anchor --simulation-config $(SIM_CONFIG)

nyc-weather:
	$(PYTHON) -m casuallab nyc-weather

nyc-events:
	$(PYTHON) -m casuallab nyc-events

nyc-income:
	$(PYTHON) -m casuallab nyc-income

nyc-benchmark:
	$(PYTHON) -m casuallab nyc-benchmark

nyc-graph-benchmark:
	$(PYTHON) -m casuallab nyc-graph-benchmark

equilibrium-benchmark:
	$(PYTHON) -m casuallab equilibrium-benchmark

build-panel:
	$(PYTHON) -m casuallab build-panel --config $(SAMPLE_CONFIG)

simulate:
	$(PYTHON) -m casuallab simulate --config $(SIM_CONFIG)

benchmark:
	$(PYTHON) -m casuallab benchmark --config $(BENCHMARK_CONFIG)

interference-benchmark:
	$(PYTHON) -m casuallab interference-benchmark

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

reproduce-sample:
	$(PYTHON) -m casuallab reproduce-sample --config $(SAMPLE_CONFIG) --simulation-config $(SIM_CONFIG) --benchmark-config $(BENCHMARK_CONFIG) --policy-config $(POLICY_CONFIG)

report:
	$(PYTHON) -m casuallab report --benchmark artifacts/benchmarks/benchmark_results.csv

dashboard:
	$(PYTHON) -m streamlit run src/casuallab/dashboard.py
