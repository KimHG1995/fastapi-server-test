import subprocess
import sys
from pathlib import Path
from shutil import which

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


def _workflow_job(document: str, job_name: str, next_job_name: str | None) -> str:
    start = document.index(f"  {job_name}:")
    end = document.index(f"  {next_job_name}:", start) if next_job_name else len(document)
    return document[start:end]


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


def test_ci_pins_toolchain_and_defines_all_required_jobs() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in workflow
    assert "cancel-in-progress: true" in workflow
    assert 'python-version: "3.13"' in workflow
    assert "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0" in workflow
    assert 'version: "0.11.31"' in workflow
    assert "actions/checkout@v6" in workflow
    assert "actions/setup-python@v6" in workflow
    assert workflow.count("uv sync --frozen --extra dev") >= 5
    assert workflow.count("timeout-minutes:") >= 6

    for job in ("quality", "unit", "integration", "e2e", "docker", "openapi"):
        assert f"  {job}:" in workflow


def test_ci_uses_postgresql_for_database_suites_and_migrates_first() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for job_name, next_job_name in (("integration", "e2e"), ("e2e", "docker")):
        job = _workflow_job(workflow, job_name, next_job_name)
        assert "image: postgres:18.4-trixie" in job
        assert "pg_isready" in job
        assert "DATABASE_URL: postgresql+asyncpg://app:app@localhost:5432/app" in job
        assert "JWT_SECRET:" in job
        assert job.index("uv run alembic upgrade head") < job.index(
            f"uv run pytest tests/{job_name} -q"
        )


def test_ci_builds_image_and_compares_a_temporary_openapi_export() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    docker_job = _workflow_job(workflow, "docker", "openapi")
    openapi_job = _workflow_job(workflow, "openapi", None)

    assert "docker compose config" in docker_job
    assert "docker compose build api" in docker_job
    assert "scripts/export_openapi.py --output" in openapi_job
    assert "cmp -s openapi/openapi.json" in openapi_job
    assert "git diff" not in openapi_job
    assert "echo ${{" not in workflow


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
