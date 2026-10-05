.PHONY: help install db-up db-down init run backfill test test-unit lint format dbt-docs clean

START ?= 2026-09-25T05:00
END   ?= 2026-09-25T18:00

help:            ## Show this help
	@grep -E "^[a-z-]+:.*## " $(MAKEFILE_LIST) | awk -F ":.*## " '{printf "  %-12s %s\n", $$1, $$2}'

install:         ## Install Python and dbt dependencies
	pip install -r requirements-dev.txt

db-up:           ## Start local Postgres in Docker
	docker compose up -d --wait

db-down:         ## Stop local Postgres
	docker compose down

init:            ## Create schemas and raw tables
	python -m pipeline init-db

run:             ## Load every missing hour in the lookback window (what the scheduler runs)
	python -m pipeline hourly

backfill:        ## Load a range of hours: make backfill START=... END=...
	python -m pipeline backfill --start $(START) --end $(END)

test:            ## All tests (integration tests skip if Postgres is not running)
	pytest

test-unit:       ## Unit tests only
	pytest -m "not integration"

lint:            ## Lint and check formatting
	ruff check . && ruff format --check .

format:          ## Auto format
	ruff format . && ruff check --fix .

dbt-docs:        ## Build and open the dbt docs site with lineage graph
	cd dbt/supermarket && dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir .

clean:           ## Remove generated files
	rm -rf data/landing/*.csv data/archive/20* dbt/supermarket/target .pytest_cache .ruff_cache
