import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.main import create_app

APPROVED_OPERATIONS = {
    ("get", "/health/live"),
    ("get", "/health/ready"),
    ("post", "/api/v1/auth/register"),
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/refresh"),
    ("post", "/api/v1/auth/logout"),
    ("post", "/api/v1/auth/logout-all"),
    ("get", "/api/v1/users/me"),
    ("patch", "/api/v1/users/me"),
    ("post", "/api/v1/users/me/password"),
    ("get", "/api/v1/products"),
    ("get", "/api/v1/products/{product_id}"),
    ("post", "/api/v1/products"),
    ("patch", "/api/v1/products/{product_id}"),
    ("delete", "/api/v1/products/{product_id}"),
}

PROTECTED_OPERATIONS = {
    ("post", "/api/v1/auth/logout-all"),
    ("get", "/api/v1/users/me"),
    ("patch", "/api/v1/users/me"),
    ("post", "/api/v1/users/me/password"),
    ("post", "/api/v1/products"),
    ("patch", "/api/v1/products/{product_id}"),
    ("delete", "/api/v1/products/{product_id}"),
}


def _document(test_settings: Settings) -> dict[str, Any]:
    return create_app(test_settings).openapi()


def test_openapi_contains_routes_contracts_and_exact_security(
    test_settings: Settings,
) -> None:
    document = _document(test_settings)
    paths = document["paths"]
    actual_operations = {
        (method, path)
        for path, path_item in paths.items()
        for method in path_item
        if method in {"get", "post", "patch", "delete"}
    }

    assert actual_operations == APPROVED_OPERATIONS
    for method, path in APPROVED_OPERATIONS:
        operation = paths[path][method]
        if (method, path) in PROTECTED_OPERATIONS:
            assert operation["security"] == [{"HTTPBearer": []}]
        else:
            assert "security" not in operation

    schemas = document["components"]["schemas"]
    assert "ProblemDetail" in schemas
    assert "ProblemField" in schemas
    assert any(name.startswith("ApiResponse") for name in schemas)
    assert any(name.startswith("PaginatedResponse") for name in schemas)
    assert "PageMeta" in schemas


def test_openapi_problem_responses_reference_problem_detail(
    test_settings: Settings,
) -> None:
    document = _document(test_settings)
    found_statuses: set[str] = set()
    for path_item in document["paths"].values():
        for method, operation in path_item.items():
            if method not in {"get", "post", "patch", "delete"}:
                continue
            for status_code, response in operation["responses"].items():
                if status_code in {"401", "403", "404", "409", "422"}:
                    found_statuses.add(status_code)
                    schema = response["content"]["application/problem+json"]["schema"]
                    assert schema == {"$ref": "#/components/schemas/ProblemDetail"}
    assert found_statuses == {"401", "403", "404", "409", "422"}


def test_openapi_export_is_cwd_independent_deterministic_and_read_only(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    script = repository_root / "scripts" / "export_openapi.py"
    snapshot = repository_root / "openapi" / "openapi.json"
    committed = snapshot.read_bytes()
    first_target = tmp_path / "exports" / "first.json"
    second_target = tmp_path / "exports" / "second.json"
    cwd_snapshot = tmp_path / "openapi" / "openapi.json"
    cwd_snapshot.parent.mkdir()
    cwd_snapshot.write_bytes(b"stale-openapi-sentinel\n")

    for target in (first_target, second_target):
        subprocess.run(  # noqa: S603
            [sys.executable, str(script), "--output", str(target)],
            cwd=tmp_path,
            check=True,
        )

    first = first_target.read_bytes()
    second = second_target.read_bytes()
    assert first == second
    assert snapshot.read_bytes() == committed
    assert cwd_snapshot.read_bytes() == b"stale-openapi-sentinel\n"
    assert first == committed
    assert committed.endswith(b"\n")
    assert json.loads(committed)["openapi"]


def test_make_verify_gates_tests_on_the_openapi_snapshot() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    make = shutil.which("make")
    assert make is not None

    result = subprocess.run(  # noqa: S603
        [make, "--dry-run", "verify"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )

    commands = result.stdout
    assert commands.index("scripts/export_openapi.py --output") < commands.index("uv run pytest -q")
