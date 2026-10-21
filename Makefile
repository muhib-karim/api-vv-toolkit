PYTHON ?= .venv/bin/python

.PHONY: install lint typecheck test demo check llm-gate llm-gate-report screenshot

install:
	python3 -m venv .venv
	$(PYTHON) -m pip install -e '.[dev,demo]'

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

typecheck:
	$(PYTHON) -m mypy --strict src

test:
	$(PYTHON) -m pytest -q

demo:
	$(PYTHON) scripts/demo.py

check: lint typecheck test

# Live, billed: one LLM gate run. Needs API_VV_LLM_BASE_URL and API_VV_LLM_API_KEY.
# make llm-gate PROVIDER=anthropic MODEL=claude-haiku-4-5 OUT=runs/haiku/r1
llm-gate:
	PYTHON=$(PYTHON) scripts/llm_gate_experiment.sh $(OUT) $(PROVIDER) $(MODEL)

llm-gate-report:
	$(PYTHON) scripts/llm_gate_summary.py --report results/2026-10-17-llm-gate

# Headless capture of the HTML matrix used in the README (run `make demo` first).
screenshot:
	chromium --headless=new --no-sandbox --disable-gpu --hide-scrollbars --window-size=1280,1180 \
	  --screenshot=docs/assets/traceability-matrix.png "file://$(CURDIR)/runs/demo/report.html"
