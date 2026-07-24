import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def render_compose_config() -> dict[str, Any]:
    docker_cli = shutil.which("docker")
    if docker_cli is None:
        pytest.skip("Docker CLI is required to validate the Compose configuration")

    environment = os.environ.copy()
    environment["JWT_SECRET"] = "x" * 32
    result = subprocess.run(  # noqa: S603 - the resolved Docker CLI is trusted test tooling
        [docker_cli, "compose", "config", "--format", "json"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return cast(dict[str, Any], json.loads(result.stdout))


def test_compose_declares_reproducible_operational_topology() -> None:
    config = render_compose_config()
    services = config["services"]

    postgres = services["postgres"]
    assert postgres["image"] == "postgres:18.4-trixie"
    assert any(
        mount["target"] == "/var/lib/postgresql" and mount["type"] == "volume"
        for mount in postgres["volumes"]
    )
    assert "pg_isready" in " ".join(postgres["healthcheck"]["test"])

    api = services["api"]
    assert api["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert "alembic" not in " ".join(api["command"])

    migrate = services["migrate"]
    assert "alembic upgrade head" in " ".join(migrate["command"])
    assert migrate["restart"] == "no"

    rendered = json.dumps(config)
    assert "change-this-example-secret-to-a-unique-value" not in rendered
    assert "jwt_secret" not in config.get("secrets", {})


def test_docker_image_uses_frozen_production_dependencies_and_non_root_user() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text().splitlines()

    assert "FROM python:3.13.13-slim-trixie AS runtime" in dockerfile
    assert "FROM ghcr.io/astral-sh/uv:0.11.31 AS uv" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    assert "UV_CACHE_DIR=/tmp/uv-cache" in dockerfile
    assert "UV_NO_SYNC=1" in dockerfile
    assert "USER app" in dockerfile
    assert ".env" in dockerignore
    assert ".venv" in dockerignore
    assert "tests" in dockerignore
