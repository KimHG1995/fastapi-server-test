import json
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


def test_openapi_export_is_cwd_independent_and_byte_identical(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    script = repository_root / "scripts" / "export_openapi.py"
    target = repository_root / "openapi" / "openapi.json"

    subprocess.run([sys.executable, str(script)], cwd=tmp_path, check=True)  # noqa: S603
    first = target.read_bytes()
    subprocess.run([sys.executable, str(script)], cwd=tmp_path, check=True)  # noqa: S603
    second = target.read_bytes()

    assert first == second
    assert first.endswith(b"\n")
    assert json.loads(first)["openapi"]
