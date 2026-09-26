.PHONY: setup up down logs check test test-e2e types demo data chaos ledger backtest train

SCENARIO ?= worker-kill

setup:
	bash scripts/bootstrap.sh

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

check:
	uv run ruff format --check .
	uv run ruff check .
	uv run pytest -q -m "not e2e"
	cd web && npm run lint && npm run typecheck && npm run build

test:
	uv run pytest -q -m "not e2e"

# Compose mode: needs `make up` first. Worker-kill and other container-level chaos.
test-e2e:
	uv run pytest -q -s -m e2e

types:
	uv run python -m gridtwin.api.export_openapi > openapi.json
	cd web && npx --yes openapi-typescript ../openapi.json -o src/types/api.ts
	rm -f openapi.json

types-check:
	$(MAKE) types
	git diff --exit-code -- web/src/types/api.ts

demo:
	docker compose up -d --build
	uv run python scripts/wait_for_health.py
	uv run python -m gridtwin.replay.cli $(if $(DAY),--day $(DAY),)

# Scripted Chaos Scenario against the running stack: make chaos SCENARIO=worker-kill
chaos:
	uv run python scripts/wait_for_health.py
	uv run python -m gridtwin.chaos.cli $(SCENARIO)

# Command Ledger summary per interval (issued/acked/expired/failed): make ledger RUN=<run_id>
ledger:
	uv run python -m gridtwin.ledger.cli $(RUN)

data:
	uv run python -m gridtwin.marketdata.cli ingest
	uv run python -m gridtwin.marketdata.cli backfill-rt-spp
	uv run python -m gridtwin.marketdata.cli backfill-dam-spp

# Scarcity-risk model: walk-forward CV vs climatology, out-of-sample Risk Curves (seeded).
train:
	uv run python -m gridtwin.risk.train

# Offline strategy backtest (naive vs LP vs LP+risk vs perfect foresight) over the cached
# window. Run `make train` first for lp_risk's Risk Curves.
backtest:
	uv run python -m gridtwin.insights.backtest
