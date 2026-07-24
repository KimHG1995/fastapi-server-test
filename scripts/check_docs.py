import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_CHARACTER = chr(0xB7)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
IGNORED_DIRECTORIES = frozenset(
    {
        ".cache",
        ".git",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".superpowers",
        ".tox",
        ".uv-cache",
        ".venv",
        ".worktrees",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
        "venv",
    }
)


@dataclass(frozen=True)
class Diagnostic:
    path: Path
    line: int | None
    kind: Literal["forbidden-character", "broken-local-link", "read-error"]


def _is_missing_local_link(document: Path, raw_target: str) -> bool:
    target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith(("http://", "https://", "mailto:", "#", "/")):
        return False

    path_text = unquote(target.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0])
    return bool(path_text) and not (document.parent / path_text).resolve().exists()


def scan_documentation(root: Path = REPOSITORY_ROOT) -> list[Diagnostic]:
    root = root.resolve()
    diagnostics: list[Diagnostic] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in IGNORED_DIRECTORIES and not (current_path / name).is_symlink()
        )
        for name in sorted(file_names):
            path = current_path / name
            if path.suffix.lower() != ".md" or path.is_symlink():
                continue
            relative_path = path.relative_to(root)
            try:
                contents = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                diagnostics.append(Diagnostic(path=relative_path, line=None, kind="read-error"))
                continue
            diagnostics.extend(
                Diagnostic(
                    path=relative_path,
                    line=line_number,
                    kind="forbidden-character",
                )
                for line_number, line in enumerate(contents.splitlines(), start=1)
                if FORBIDDEN_CHARACTER in line
            )
            diagnostics.extend(
                Diagnostic(
                    path=relative_path,
                    line=line_number,
                    kind="broken-local-link",
                )
                for line_number, line in enumerate(contents.splitlines(), start=1)
                for target in MARKDOWN_LINK.findall(line)
                if _is_missing_local_link(path, target)
            )
    return diagnostics


def main(root: Path = REPOSITORY_ROOT) -> int:
    diagnostics = scan_documentation(root)
    for diagnostic in diagnostics:
        location = (
            f"{diagnostic.path}:{diagnostic.line}"
            if diagnostic.line is not None
            else str(diagnostic.path)
        )
        messages = {
            "forbidden-character": "forbidden documentation character",
            "broken-local-link": "broken local Markdown link",
            "read-error": "unable to read Markdown as UTF-8",
        }
        message = messages[diagnostic.kind]
        print(f"{location}: {message}", file=sys.stderr)
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
