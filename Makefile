PYTHON ?= .venv\Scripts\python.exe
PIP ?= .venv\Scripts\pip.exe

.PHONY: help setup up down restart logs ps seed test test-contracts test-integration lint format smoke demo-query demo-connection reset

help:
	@echo "setup             Install Python dependencies"
	@echo "up                Build and start the local stack"
	@echo "down              Stop the local stack"
	@echo "restart           Restart the local stack"
	@echo "logs              Follow Docker Compose logs"
	@echo "ps                Show service status"
	@echo "seed               Seed deterministic MongoDB orders"
	@echo "test               Run all Python tests"
	@echo "test-contracts     Validate schemas and contract examples"
	@echo "test-integration   Run shared-pipeline integration tests"
	@echo "lint               Run Ruff checks"
	@echo "format             Format Python with Ruff"
	@echo "smoke              Verify a running Docker stack"
	@echo "demo-query         Run the mock query-regression flow"
	@echo "demo-connection    Run the mock connection-pressure flow"
	@echo "reset              Stop stack and remove local Docker volumes"

setup:
	python -m venv .venv
	$(PIP) install -e ".[dev]"

up:
	docker compose up -d --build

down:
	docker compose down

restart: down up

logs:
	docker compose logs -f

ps:
	docker compose ps

seed:
	docker compose exec analysis-service python scripts/seed_orders.py --uri "mongodb://app_user:app_password@mongo:27017/reliability_demo?authSource=reliability_demo"

test:
	$(PYTHON) -m pytest

test-contracts:
	$(PYTHON) -m pytest tests/contracts

test-integration:
	$(PYTHON) -m pytest tests/integration

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

smoke:
	powershell -ExecutionPolicy Bypass -File scripts\smoke_test.ps1

demo-query:
	powershell -ExecutionPolicy Bypass -Command "$$response = Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/v1/dev/mock/query-regression'; $$response | ConvertTo-Json -Depth 10; Write-Host ('Report: http://localhost:8000/analyses/' + $$response.analysisId + '/report')"

demo-connection:
	powershell -ExecutionPolicy Bypass -Command "$$response = Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/api/v1/dev/mock/connection-pressure'; $$response | ConvertTo-Json -Depth 10; Write-Host ('Report: http://localhost:8000/analyses/' + $$response.analysisId + '/report')"

reset:
	docker compose down -v --remove-orphans