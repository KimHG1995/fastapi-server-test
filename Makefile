.PHONY: install run test lint format typecheck migrate create-admin openapi docs-check \
	docker-config docker-build docker-postgres docker-migrate docker-up docker-down

install:
	uv sync --extra dev

run:
	uv run uvicorn app.main:create_app --factory --reload

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format --check .

typecheck:
	uv run mypy app tests

migrate:
	uv run alembic upgrade head

create-admin:
	uv run python -m app.cli create-admin --email "$(EMAIL)" --display-name "$(DISPLAY_NAME)"

openapi:
	uv run python scripts/export_openapi.py

docs-check:
	uv run --extra dev python scripts/check_docs.py

docker-config:
	docker compose config

docker-build:
	docker compose build api

docker-postgres:
	docker compose up -d postgres

docker-migrate:
	docker compose run --rm migrate

docker-up:
	docker compose up --build api

docker-down:
	docker compose down
