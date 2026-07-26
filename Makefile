.PHONY: install run test lint format typecheck lock-check migrate create-admin openapi \
	openapi-check docs-check verify docker-config docker-build docker-postgres \
	docker-migrate docker-up docker-down

install:
	uv sync --extra dev

run:
	uv run uvicorn app.main:create_app --factory --reload

test:
	uv run pytest -q

lint:
	uv run ruff check .

format:
	uv run ruff format --check .

typecheck:
	uv run mypy app tests scripts

lock-check:
	uv lock --check

migrate:
	uv run alembic upgrade head

create-admin:
	uv run python -m app.cli create-admin --email "$(EMAIL)" --display-name "$(DISPLAY_NAME)"

openapi:
	uv run python scripts/export_openapi.py

openapi-check:
	@temporary_file="$$(mktemp)"; \
	trap 'rm -f "$$temporary_file"' EXIT; \
	uv run python scripts/export_openapi.py --output "$$temporary_file"; \
	cmp -s openapi/openapi.json "$$temporary_file"

docs-check:
	uv run --extra dev python scripts/check_docs.py

verify: lock-check lint format typecheck docs-check openapi-check
	$(MAKE) test

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
