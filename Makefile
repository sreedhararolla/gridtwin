.PHONY: setup up down logs check test test-e2e types demo

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
	uv run pytest -q
	cd web && npm run lint && npm run typecheck && npm run build

test:
	uv run pytest -q

test-e2e:
	uv run pytest -q -m e2e

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
	uv run python -m gridtwin.replay.cli
