import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from pytest import MonkeyPatch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRET_SENTINEL = "compose-secret-must-not-appear-" + ("x" * 32)


def render_compose_config(
    *,
    env_file: Path | None = None,
    environment_overrides: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str]:
    docker_cli = shutil.which("docker")
    assert docker_cli is not None, "Docker CLI is required to validate Compose configuration"

    environment = os.environ.copy()
    environment["JWT_SECRET"] = SECRET_SENTINEL
    environment.update(environment_overrides or {})
    command = [docker_cli, "compose"]
    if env_file is not None:
        command.extend(["--env-file", str(env_file)])
    command.extend(["config", "--format", "json"])
    result = subprocess.run(  # noqa: S603 - the resolved Docker CLI is trusted test tooling
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return cast(dict[str, Any], json.loads(result.stdout)), result.stdout


def test_compose_declares_reproducible_operational_topology() -> None:
    config, rendered = render_compose_config()
    services = config["services"]

    postgres = services["postgres"]
    assert postgres["image"] == "postgres:18.4-trixie"
    assert any(
        mount["target"] == "/var/lib/postgresql" and mount["type"] == "volume"
        for mount in postgres["volumes"]
    )
    assert "pg_isready" in " ".join(postgres["healthcheck"]["test"])
    assert len(postgres["ports"]) == 1
    postgres_port = postgres["ports"][0]
    assert postgres_port["host_ip"] == "127.0.0.1"
    assert postgres_port["published"] == "5432"
    assert postgres_port["target"] == 5432

    api = services["api"]
    assert api["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert api["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert "alembic" not in " ".join(api["command"])

    migrate = services["migrate"]
    assert "alembic upgrade head" in " ".join(migrate["command"])
    assert migrate["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert "migrate" not in migrate["depends_on"]
    assert migrate["restart"] == "no"

    assert "change-this-example-secret-to-a-unique-value" not in rendered
    assert SECRET_SENTINEL not in rendered
    assert config["secrets"]["jwt_secret"]["environment"] == "JWT_SECRET"
    for service_name in ("api", "migrate"):
        service = services[service_name]
        assert "JWT_SECRET" not in service["environment"]
        assert any(
            secret["source"] == "jwt_secret"
            and f"/run/secrets/{secret['target']}" == "/run/secrets/jwt_secret"
            for secret in service["secrets"]
        )


def test_compose_ignores_host_database_url_and_builds_internal_url_from_db_settings() -> None:
    config, _ = render_compose_config(
        env_file=PROJECT_ROOT / ".env.example",
        environment_overrides={
            "POSTGRES_USER": "compose_user",
            "POSTGRES_PASSWORD": "compose_password",
            "POSTGRES_DB": "compose_database",
        },
    )
    services = config["services"]
    expected_url = (
        "postgresql+asyncpg://compose_user:compose_password@postgres:5432/compose_database"
    )

    assert services["postgres"]["environment"] == {
        "POSTGRES_DB": "compose_database",
        "POSTGRES_PASSWORD": "compose_password",
        "POSTGRES_USER": "compose_user",
    }
    assert services["api"]["environment"]["DATABASE_URL"] == expected_url
    assert services["migrate"]["environment"]["DATABASE_URL"] == expected_url
    assert "localhost" not in services["api"]["environment"]["DATABASE_URL"]


def test_compose_keeps_postgres_loopback_binding_when_host_port_is_overridden() -> None:
    config, _ = render_compose_config(
        environment_overrides={"POSTGRES_PORT": "15432"},
    )

    ports = config["services"]["postgres"]["ports"]
    assert len(ports) == 1
    assert ports[0]["host_ip"] == "127.0.0.1"
    assert ports[0]["published"] == "15432"
    assert ports[0]["target"] == 5432


def test_compose_cli_is_a_required_test_dependency(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda executable: None)

    with pytest.raises(AssertionError, match="Docker CLI"):
        render_compose_config()


def test_docker_image_uses_frozen_production_dependencies_and_non_root_user() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text().splitlines()

    assert "FROM python:3.13.13-slim-trixie AS runtime" in dockerfile
    assert "FROM ghcr.io/astral-sh/uv:0.11.31 AS uv" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    dependency_copy = dockerfile.index("COPY pyproject.toml uv.lock ./")
    dependency_sync = dockerfile.index("RUN uv sync --frozen --no-dev --no-install-project")
    readme_copy = dockerfile.index("COPY README.md")
    assert dependency_copy < dependency_sync < readme_copy
    assert "UV_CACHE_DIR=/tmp/uv-cache" in dockerfile
    assert "UV_NO_SYNC=1" in dockerfile
    assert "USER app" in dockerfile
    assert ".env" in dockerignore
    assert ".venv" in dockerignore
    assert "tests" in dockerignore
