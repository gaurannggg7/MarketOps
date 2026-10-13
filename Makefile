# MarketOps developer commands. `make help` lists targets.
SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend
PY := $(BACKEND)/.venv/bin/python
VENV_BIN := $(BACKEND)/.venv/bin

.DEFAULT_GOAL := help

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

env: ## Create .env with generated local demo passwords (never overwrites)
	python3 scripts/make_env.py

install: ## Install backend (venv, hashed lockfile) and frontend (npm ci) dependencies
	test -d $(BACKEND)/.venv || python3.13 -m venv $(BACKEND)/.venv || python3 -m venv $(BACKEND)/.venv
	$(VENV_BIN)/pip install --require-hashes -r $(BACKEND)/requirements-dev.lock
	cd $(FRONTEND) && npm ci

db-up: ## Start PostgreSQL (Docker Compose) and wait for it to be healthy
	docker compose up -d --wait db

db-down: ## Stop containers (data volume is kept)
	docker compose down

migrate: ## Apply Alembic migrations to the configured database
	cd $(BACKEND) && .venv/bin/alembic upgrade head

seed: ## Idempotent demo seed: users, 200 synthetic instruments, default rules
	cd $(BACKEND) && .venv/bin/python -m app.seed

seed-reset: ## LOCAL ONLY: wipe business tables, then seed
	cd $(BACKEND) && .venv/bin/python -m app.seed --reset

fixtures: ## Load 100k synthetic historical events (benchmark fixture)
	cd $(BACKEND) && .venv/bin/python -m app.seed events --count 100000

prune: ## Apply quote-sample retention now
	cd $(BACKEND) && .venv/bin/python -m app.seed prune

dev-backend: ## Run FastAPI (single worker) on :8000
	cd $(BACKEND) && .venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000

dev-frontend: ## Run Vite on :5173 (proxies /api and /ws to :8000)
	cd $(FRONTEND) && npm run dev

api-types: ## Regenerate OpenAPI JSON and TypeScript types from the backend
	cd $(BACKEND) && .venv/bin/python -m app.export_openapi ../$(FRONTEND)/src/lib/api/openapi.json
	cd $(FRONTEND) && npm run --silent api-types

api-check: api-types ## Fail if committed API types differ from the backend contract
	git diff --exit-code -- $(FRONTEND)/src/lib/api/openapi.json $(FRONTEND)/src/lib/api/schema.d.ts

lint: ## Ruff + ESLint
	cd $(BACKEND) && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd $(FRONTEND) && npm run --silent lint

typecheck: ## mypy (strict) + tsc
	cd $(BACKEND) && .venv/bin/mypy app tests
	cd $(FRONTEND) && npm run --silent typecheck

test-backend: ## pytest against PostgreSQL (creates/drops marketops_test)
	cd $(BACKEND) && .venv/bin/pytest -q

test-frontend: ## Vitest + React Testing Library
	cd $(FRONTEND) && npm test --silent

build: ## Frontend production build + backend import check
	cd $(FRONTEND) && npm run --silent build
	cd $(BACKEND) && .venv/bin/python -c "import app.main; print('backend import ok')"

check: lint typecheck test-backend test-frontend build ## All local quality gates (except E2E)

e2e: ## Playwright workflows (starts its own backend + frontend on dedicated ports/DB)
	cd $(FRONTEND) && npx playwright test

bench: ## Workload benchmark (see docs/performance.md)
	$(PY) scripts/benchmark.py

secrets-scan: ## Grep tracked files for likely committed secrets
	bash scripts/secret_scan.sh

images: ## Build versioned Docker images
	docker compose --profile app build

stack-up: ## Run the full containerized stack (db + backend + nginx web on :8080)
	docker compose --profile app up -d --wait

stack-seed: ## Seed the containerized database
	docker compose --profile app exec backend python -m app.seed

smoke: ## Smoke checks against a running stack (default http://localhost:8080)
	$(PY) scripts/smoke.py

.PHONY: help env install db-up db-down migrate seed seed-reset fixtures prune dev-backend dev-frontend api-types api-check lint typecheck test-backend test-frontend build check e2e bench secrets-scan images stack-up stack-seed smoke
