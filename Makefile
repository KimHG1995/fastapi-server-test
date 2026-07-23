.PHONY: install run test lint format typecheck

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
