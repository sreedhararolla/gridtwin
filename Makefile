.PHONY: setup up down logs check test test-e2e types demo demo-full data chaos ledger backtest train insights bench

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

# The video's scenario: worker kill, partition, duplicates, feed outage on the top spike
# day. Prints the Scenario Report and SLO table; exits non-zero if any SLO is missed.
demo-full:
	docker compose up -d --build
	uv run python scripts/wait_for_health.py
	uv run python -m gridtwin.chaos.cli demo-full

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

# Value concentration + downtime-cost heatmap from the cache: insights.json for the
# Insights tab, plus the same numbers as CSV (and the heatmap as SVG) in data/cache/insights/.
insights:
	uv run python -X utf8 -m gridtwin.insights.report

# Scale benchmark matrix (1k/5k/10k/20k devices, worker kill, planner, 30-minute memory
# soak) on its own infra (docker-compose.bench.yml), then BENCHMARKS.md. About 50 minutes;
# BENCH_SIZES / BENCH_SOAK_MINUTES shorten it. The demo stack can stay up.
BENCH_POSTGRES_PORT ?= 25432
BENCH_NATS_PORT ?= 24222
BENCH_TEMPORAL_PORT ?= 27233
BENCH_PORTS = BENCH_POSTGRES_PORT=$(BENCH_POSTGRES_PORT) BENCH_NATS_PORT=$(BENCH_NATS_PORT) BENCH_TEMPORAL_PORT=$(BENCH_TEMPORAL_PORT)
BENCH_COMPOSE = docker compose -p gridtwin-bench -f docker-compose.yml -f docker-compose.bench.yml

bench:
	$(BENCH_PORTS) $(BENCH_COMPOSE) up -d --wait postgres nats
	$(BENCH_PORTS) $(BENCH_COMPOSE) up -d temporal
	POSTGRES_DSN=postgresql://gridtwin:gridtwin@localhost:$(BENCH_POSTGRES_PORT)/gridtwin \
	NATS_URL=nats://localhost:$(BENCH_NATS_PORT) \
	TEMPORAL_ADDRESS=localhost:$(BENCH_TEMPORAL_PORT) \
	TASK_QUEUE=gridtwin-bench \
		uv run python -X utf8 -m gridtwin.bench.cli
