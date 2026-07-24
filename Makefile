.PHONY: install run test lint format typecheck create-admin openapi docs-check

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

create-admin:
	uv run python -m app.cli create-admin --email "$(EMAIL)" --display-name "$(DISPLAY_NAME)"

openapi:
	uv run python scripts/export_openapi.py

docs-check:
	uv run python scripts/check_docs.py
