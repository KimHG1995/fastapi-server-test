from pathlib import Path

from scripts import check_docs

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
README = REPOSITORY_ROOT / "README.md"
SUPPORTING_DOCUMENTS = (
    REPOSITORY_ROOT / "docs" / "architecture.md",
    REPOSITORY_ROOT / "docs" / "node-python-runtime.md",
)


def test_readme_covers_the_runtime_contract_and_frontend_workflow() -> None:
    readme = README.read_text(encoding="utf-8")
    required_phrases = (
        "FastAPI",
        "Starlette",
        "ASGI",
        "Uvicorn",
        "V8",
        "libuv",
        "event loop",
        "CPython",
        "GIL",
        "thread pool",
        "worker process",
        "Promise",
        "Coroutine",
        "Task",
        "asyncio.gather",
        "NestJS",
        "Pydantic",
        "Zod",
        "SQLAlchemy",
        "Alembic",
        "/docs",
        "/redoc",
        "/openapi.json",
        "openapi-typescript",
        "Orval",
        "docker compose run --rm migrate",
        "Access Token은 로그아웃 후에도 최대 15분 동안 유효할 수 있습니다",
    )

    missing = [phrase for phrase in required_phrases if phrase not in readme]

    assert missing == []


def test_documented_commands_match_repository_entry_points() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "uv run uvicorn app.main:create_app --factory --reload" in readme
    assert "uv run alembic upgrade head" in readme
    assert "uv run python -m app.cli create-admin" in readme
    assert "uv run python scripts/export_openapi.py" in readme
    assert "npx openapi-typescript ./openapi/openapi.json -o src/api/schema.d.ts" in readme


def test_every_local_markdown_link_points_to_an_existing_target() -> None:
    assert all(document.is_file() for document in (README, *SUPPORTING_DOCUMENTS))
    assert check_docs.scan_documentation(REPOSITORY_ROOT) == []


def test_architecture_documents_actual_middleware_request_order() -> None:
    architecture = SUPPORTING_DOCUMENTS[0].read_text(encoding="utf-8")

    request_context = architecture.index("-> RequestContextMiddleware")
    cors = architecture.index("-> CORS")

    assert request_context < cors


def test_documentation_checker_supports_markdown_link_forms_and_anchors(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "diagram(one).png").write_bytes(b"image")
    (tmp_path / "README.md").write_text("# Overview\n", encoding="utf-8")
    (docs / "file with spaces.md").write_text(
        "# Encoded heading (v2)\n",
        encoding="utf-8",
    )
    (docs / "reference.md").write_text("# Reference heading\n", encoding="utf-8")
    (docs / "guide.md").write_text(
        "\n".join(
            (
                "# Local heading",
                "[same](#local-heading)",
                "[cross](../README.md#overview)",
                "[angle](<file with spaces.md#encoded-heading-v2>)",
                "[encoded](file%20with%20spaces.md#encoded-heading-v2)",
                "[encoded fragment](reference.md#reference%2Dheading)",
                "![inline image](../assets/diagram(one).png)",
                "[reference link][reference]",
                "![reference image][image]",
                "[http](http://example.com/a_(b))",
                "[https](https://example.com)",
                "[mail](mailto:learner@example.com)",
                "[data](data:image/png;base64,AAAA)",
                "[ftp](ftp://example.com/file.txt)",
                "",
                "[reference]: reference.md#reference-heading",
                "[image]: ../assets/diagram(one).png",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    assert check_docs.scan_documentation(tmp_path) == []


def test_documentation_checker_reports_missing_files_references_and_anchors(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text("# Existing heading\n", encoding="utf-8")
    (docs / "guide.md").write_text(
        "\n".join(
            (
                "# Guide",
                "[same anchor](#missing-heading)",
                "[cross anchor](target.md#missing-heading)",
                "![missing image](missing.png)",
                "[missing reference][unknown]",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    diagnostics = check_docs.scan_documentation(tmp_path)

    assert [(item.path.as_posix(), item.line, item.kind) for item in diagnostics] == [
        ("docs/guide.md", 2, "broken-local-link"),
        ("docs/guide.md", 3, "broken-local-link"),
        ("docs/guide.md", 4, "broken-local-link"),
        ("docs/guide.md", 5, "broken-local-link"),
    ]


def test_documentation_checker_returns_nonzero_for_broken_anchor(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text(
        "# Existing\n\n[broken](#missing)\n",
        encoding="utf-8",
    )

    assert check_docs.main(tmp_path) == 1
