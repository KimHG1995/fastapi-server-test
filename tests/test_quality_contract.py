import subprocess
import sys
import tomllib
from pathlib import Path
from shutil import which
from typing import Any, cast

import pytest
import yaml  # type: ignore[import-untyped]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"
EXPECTED_JOBS = {"quality", "unit", "integration", "e2e", "docker", "openapi"}
PYTHON_JOBS = EXPECTED_JOBS
SETUP_UV_ACTION = "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b"


def _load_workflow_text(contents: str) -> dict[str, Any]:
    document = yaml.safe_load(contents)
    assert isinstance(document, dict), "workflow must be a YAML mapping"
    return cast(dict[str, Any], document)


def _load_workflow() -> dict[str, Any]:
    return _load_workflow_text(WORKFLOW.read_text(encoding="utf-8"))


def _jobs(document: dict[str, Any]) -> dict[str, Any]:
    jobs = document.get("jobs")
    assert isinstance(jobs, dict), "jobs must be a mapping"
    return cast(dict[str, Any], jobs)


def _job(jobs: dict[str, Any], name: str) -> dict[str, Any]:
    job = jobs.get(name)
    assert isinstance(job, dict), f"{name} must be a mapping"
    return cast(dict[str, Any], job)


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = job.get("steps")
    assert isinstance(raw_steps, list), "steps must be a list"
    assert all(isinstance(step, dict) for step in raw_steps)
    return cast(list[dict[str, Any]], raw_steps)


def _run_steps(job: dict[str, Any]) -> list[str]:
    return [command for step in _steps(job) if isinstance(command := step.get("run"), str)]


def _executable_run_lines(job: dict[str, Any]) -> list[str]:
    return [
        line
        for command in _run_steps(job)
        for raw_line in command.splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]


def _uses_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in _steps(job) if isinstance(step.get("uses"), str)]


def _uses_step(job: dict[str, Any], action: str) -> dict[str, Any]:
    matches = [step for step in _uses_steps(job) if step["uses"] == action]
    assert len(matches) == 1, f"{action} must appear exactly once"
    return matches[0]


def _run_step_index(job: dict[str, Any], exact_command: str) -> int:
    commands = _run_steps(job)
    assert exact_command in commands, f"missing exact run step: {exact_command}"
    return commands.index(exact_command)


def test_make_verify_runs_every_release_gate_without_overwriting_openapi() -> None:
    make = which("make")
    assert make is not None
    result = subprocess.run(  # noqa: S603 - resolved system build tool
        [make, "--dry-run", "verify"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    commands = result.stdout
    required_commands = (
        "uv lock --check",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run mypy app tests scripts",
        "uv run --extra dev python scripts/check_docs.py",
        "uv run pytest -q",
        "uv run python scripts/export_openapi.py --output",
        "cmp -s openapi/openapi.json",
    )

    assert all(command in commands for command in required_commands)
    assert "git diff" not in commands


def test_pyyaml_is_a_direct_development_dependency() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    development_dependencies = project["project"]["optional-dependencies"]["dev"]

    assert "pyyaml==6.0.3" in development_dependencies


def test_ci_yaml_has_the_required_job_schema_and_controls() -> None:
    document = _load_workflow()
    jobs = _jobs(document)

    assert set(jobs) == EXPECTED_JOBS
    assert document["permissions"] == {"contents": "read"}
    assert document["concurrency"]["cancel-in-progress"] is True

    for job_name in EXPECTED_JOBS:
        job = _job(jobs, job_name)
        assert isinstance(job.get("timeout-minutes"), int)
        assert job["timeout-minutes"] > 0
        assert _steps(job)


def test_every_python_job_uses_the_exact_pinned_toolchain_and_frozen_sync() -> None:
    jobs = _jobs(_load_workflow())

    for job_name in PYTHON_JOBS:
        job = _job(jobs, job_name)
        _uses_step(job, "actions/checkout@v6")

        setup_python = _uses_step(job, "actions/setup-python@v6")
        assert setup_python.get("with") == {"python-version": "3.13"}

        setup_uv = _uses_step(job, SETUP_UV_ACTION)
        assert setup_uv.get("with") == {"version": "0.11.31"}

        assert "uv sync --frozen --extra dev" in _run_steps(job)


def test_quality_and_unit_jobs_run_their_exact_test_suites() -> None:
    jobs = _jobs(_load_workflow())
    quality = _job(jobs, "quality")
    unit = _job(jobs, "unit")

    assert "uv run pytest tests/test_quality_contract.py -q" in _run_steps(quality)
    assert "uv run pytest tests/unit tests/documentation -q" in _run_steps(unit)


def test_database_jobs_use_postgresql_and_migrate_before_tests() -> None:
    jobs = _jobs(_load_workflow())

    for job_name in ("integration", "e2e"):
        job = _job(jobs, job_name)
        environment = job.get("env")
        assert isinstance(environment, dict)
        assert environment["DATABASE_URL"] == ("postgresql+asyncpg://app:app@localhost:5432/app")
        assert isinstance(environment["JWT_SECRET"], str)
        assert len(environment["JWT_SECRET"]) >= 32

        services = job.get("services")
        assert isinstance(services, dict)
        postgres = services.get("postgres")
        assert isinstance(postgres, dict)
        assert postgres["image"] == "postgres:18.4-trixie"
        assert postgres["env"] == {
            "POSTGRES_DB": "app",
            "POSTGRES_USER": "app",
            "POSTGRES_PASSWORD": "app",
        }
        assert postgres["ports"] == ["5432:5432"]
        assert "pg_isready -U app -d app" in postgres["options"]

        pytest_command = f"uv run pytest tests/{job_name} -q"
        assert _run_step_index(job, "uv run alembic upgrade head") < _run_step_index(
            job,
            pytest_command,
        )


def test_docker_and_openapi_jobs_run_their_real_commands() -> None:
    jobs = _jobs(_load_workflow())
    docker = _job(jobs, "docker")
    openapi = _job(jobs, "openapi")

    assert "uv run pytest tests/operations -q" in _run_steps(docker)
    assert "docker compose config" in _run_steps(docker)
    assert "docker compose build api" in _run_steps(docker)

    openapi_lines = _executable_run_lines(openapi)
    assert 'temporary_file="$(mktemp)"' in openapi_lines
    assert 'uv run python scripts/export_openapi.py --output "$temporary_file"' in openapi_lines
    assert 'cmp -s openapi/openapi.json "$temporary_file"' in openapi_lines


def test_ci_run_steps_never_echo_environment_or_expressions() -> None:
    jobs = _jobs(_load_workflow())

    for job_name in EXPECTED_JOBS:
        lines = _executable_run_lines(_job(jobs, job_name))
        assert all(not line.startswith("echo ") for line in lines)
        assert all("${{" not in line for line in lines)


def test_commented_yaml_and_shell_commands_do_not_satisfy_run_contracts() -> None:
    document = _load_workflow_text(
        """
jobs:
  quality:
    timeout-minutes: 10
    steps:
      # - run: uv run pytest tests/test_quality_contract.py -q
      - run: |
          # uv run pytest tests/test_quality_contract.py -q
          uv sync --frozen --extra dev
"""
    )
    quality = _job(_jobs(document), "quality")

    assert "uv run pytest tests/test_quality_contract.py -q" not in _run_steps(quality)
    assert "uv run pytest tests/test_quality_contract.py -q" not in _executable_run_lines(quality)


def test_malformed_yaml_is_rejected() -> None:
    with pytest.raises(yaml.YAMLError):
        _load_workflow_text("jobs:\n  quality:\n    steps: [\n")


def test_openapi_export_can_target_a_temporary_file_without_touching_snapshot(
    tmp_path: Path,
) -> None:
    snapshot = PROJECT_ROOT / "openapi" / "openapi.json"
    before = snapshot.read_bytes()
    temporary_export = tmp_path / "openapi.json"

    subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "export_openapi.py"),
            "--output",
            str(temporary_export),
        ],
        cwd=tmp_path,
        check=True,
    )

    assert snapshot.read_bytes() == before
    assert temporary_export.read_bytes() == before
