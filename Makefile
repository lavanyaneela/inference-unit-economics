# `make verify` is the one command this repository promises a reviewer. It must
# pass from a fresh clone with no network at runtime, so every target below reads
# committed fixtures rather than reaching for a cloud, a pricing API, or a
# benchmark of the machine it happens to be on.

PY ?= python3
PKG = inference_unit_economics

.PHONY: help install lint test experiments receipts prove verify decide table \
        crossovers report terraform profile model evidence diagrams clean

help:
	@echo "install       editable install with dev extras"
	@echo "lint          ruff over src, tests, tools, experiments"
	@echo "test          pytest with junit and coverage reports"
	@echo "experiments   re-run E1 to E5 into docs/experiments"
	@echo "receipts      re-measure every published figure and check the documents"
	@echo "prove         watch the number checker fail on a deliberately broken figure"
	@echo "verify        lint + test + receipts. Offline at runtime. The command that matters."
	@echo "decide        run the headline decision and report its exit code"
	@echo "report        write the HTML report to docs/evidence"
	@echo "terraform     regenerate the committed .tf files"
	@echo "profile       re-measure THIS machine and overwrite the committed profile"
	@echo "model         rebuild the ONNX fixture (needs the train extra)"
	@echo "evidence      diagrams and screenshots"

install:
	$(PY) -m pip install -e ".[dev]"

lint:
	ruff check src tests tools experiments

test:
	mkdir -p reports
	$(PY) -m pytest -q --junitxml=reports/junit.xml \
		--cov=$(PKG) --cov-report=json:reports/coverage.json --cov-report=term

experiments:
	cd experiments && PYTHONPATH=. $(PY) e1_throughput_profile.py
	cd experiments && PYTHONPATH=. $(PY) e2_cost_table.py
	cd experiments && PYTHONPATH=. $(PY) e3_crossovers.py
	cd experiments && PYTHONPATH=. $(PY) e4_sensitivity.py
	cd experiments && PYTHONPATH=. $(PY) e5_terraform_coverage.py

# Runs the suite and the experiments itself when called directly. CI calls the
# collector with --skip-tests after running the suite as its own step, so a red
# test surfaces as a red test rather than as a traceback from a metrics script.
receipts:
	$(PY) tools/collect_metrics.py
	$(PY) tools/check_numbers.py
	$(PY) tools/check_durations.py

prove:
	$(PY) tools/check_numbers.py --prove

verify: lint test receipts

# make returns 2 for any failed recipe, which would collapse the tool's exit 1
# and exit 2 into one number and destroy the distinction this repository is
# about. The recipe therefore reports the tool's own code and always succeeds
# itself. Branch on the `iue` console script, never on make.
decide:
	@$(PY) -m $(PKG).cli decide; code=$$?; echo; \
		echo "inference-unit-economics exited $$code"; exit 0

table:
	@$(PY) -m $(PKG).cli table --latency deferred

crossovers:
	@$(PY) -m $(PKG).cli crossovers

report:
	$(PY) -m $(PKG).cli report --out docs/evidence/report.html
	$(PY) -m $(PKG).cli report --out docs/evidence/report-refused.html --max-band-pct 10

terraform:
	$(PY) -m $(PKG).tfgen.generate

profile:
	$(PY) -m $(PKG).bench.harness

model:
	$(PY) -m $(PKG).model.build

diagrams:
	$(PY) tools/render_diagrams.py

evidence: diagrams report
	$(PY) tools/capture_screenshots.py
	$(PY) tools/check_readme_render.py

clean:
	rm -rf reports .pytest_cache .ruff_cache .coverage coverage.json
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# The candidate's GitHub handle is a placeholder until they supply it. Badges and
# clone URLs read from it, and a placeholder left in a badge renders as
# "unknown", which is the first thing a reviewer notices.
HANDLE ?=
set-handle:
	@test -n "$(HANDLE)" || (echo "usage: make set-handle HANDLE=yourname" && exit 1)
	@grep -rl GITHUB_USERNAME README.md docs 2>/dev/null | xargs -r sed -i.bak "s/GITHUB_USERNAME/$(HANDLE)/g"
	@find . -name "*.bak" -delete
	@echo "set the handle to $(HANDLE) in README.md and docs/"
.PHONY: set-handle
