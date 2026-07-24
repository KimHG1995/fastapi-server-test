import re
from pathlib import Path
from urllib.parse import unquote

from scripts import check_docs

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
README = REPOSITORY_ROOT / "README.md"
SUPPORTING_DOCUMENTS = (
    REPOSITORY_ROOT / "docs" / "architecture.md",
    REPOSITORY_ROOT / "docs" / "node-python-runtime.md",
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")


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
    documents = (README, *SUPPORTING_DOCUMENTS)
    missing: list[str] = []

    for document in documents:
        contents = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(contents):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target_path = unquote(target.split("#", maxsplit=1)[0])
            if not (document.parent / target_path).resolve().exists():
                missing.append(f"{document.relative_to(REPOSITORY_ROOT)} -> {target}")

    assert missing == []


def test_documentation_checker_reports_missing_local_markdown_links(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "existing.md").write_text("# Existing\n", encoding="utf-8")
    (docs / "guide.md").write_text(
        "\n".join(
            (
                "[valid](../existing.md)",
                "[missing](missing.md)",
                "[remote](https://fastapi.tiangolo.com/)",
                "[heading](#local-heading)",
            )
        ),
        encoding="utf-8",
    )

    diagnostics = check_docs.scan_documentation(tmp_path)

    assert [(item.path.as_posix(), item.line, item.kind) for item in diagnostics] == [
        ("docs/guide.md", 2, "broken-local-link")
    ]
