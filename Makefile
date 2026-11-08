# Shortcuts for everything in this repo. Run `make` to see them.
.DEFAULT_GOAL := help
PYTHON ?= python3

.PHONY: help install lint format test rules alert-tests routing ci up check game-day gate report down

help: ## Show this list
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-12s %s\n", $$1, $$2}'

install: ## Install the Python tools
	$(PYTHON) -m pip install -r requirements-dev.txt

lint: ## Lint Python and shell scripts
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	shellcheck -x scripts/*.sh

format: ## Format the Python code
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

test: ## Unit tests: app, gate, report, dashboard
	$(PYTHON) -m pytest -q

rules: ## Regenerate the SLO rules from slos/checkout.yaml (needs sloth)
	scripts/generate-slo-rules.sh

alert-tests: ## Replay fake traffic and check which alerts fire (needs promtool)
	scripts/test-slo-rules.sh

routing: ## Check where each alert lands (needs amtool, yq)
	scripts/test-alert-routing.sh

ci: lint test alert-tests routing ## Everything CI checks without a cluster

up: ## Start the lab on kind
	scripts/up.sh

check: ## Check Prometheus is scraping checkout traffic
	scripts/check.sh

game-day: ## Run the outage drill and print the timeline
	scripts/game-day.sh

gate: ## Ask the deploy gate
	scripts/gate.sh

report: ## Print where every SLO stands
	scripts/slo-report.sh

down: ## Delete the lab cluster
	scripts/down.sh
