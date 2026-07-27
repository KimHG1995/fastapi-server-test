from pathlib import Path

import pytest

from scripts import check_docs


def test_scan_documentation_reports_all_nested_violations_and_lines(tmp_path: Path) -> None:
    forbidden = chr(0xB7)
    nested = tmp_path / "docs" / "nested"
    nested.mkdir(parents=True)
    (tmp_path / "README.md").write_text(f"clean\nbad {forbidden}\n", encoding="utf-8")
    (nested / "guide.md").write_text(
        f"{forbidden} first\nclean\n{forbidden} third\n",
        encoding="utf-8",
    )

    diagnostics = check_docs.scan_documentation(tmp_path)

    assert [(item.path.as_posix(), item.line) for item in diagnostics] == [
        ("README.md", 2),
        ("docs/nested/guide.md", 1),
        ("docs/nested/guide.md", 3),
    ]
    assert all(item.kind == "forbidden-character" for item in diagnostics)


def test_scan_documentation_ignores_generated_directories_and_symlinks(
    tmp_path: Path,
) -> None:
    forbidden = chr(0xB7)
    ignored_names = (
        ".git",
        ".venv",
        ".superpowers",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "__pycache__",
        ".uv-cache",
        "node_modules",
        "build",
        "dist",
    )
    for name in ignored_names:
        directory = tmp_path / name
        directory.mkdir()
        (directory / "ignored.md").write_text(forbidden, encoding="utf-8")
    symlink_target = tmp_path / "symlink-target.txt"
    symlink_target.write_text(forbidden, encoding="utf-8")
    (tmp_path / "linked.md").symlink_to(symlink_target)
    (tmp_path / "linked-dir").symlink_to(tmp_path / ".venv", target_is_directory=True)

    assert check_docs.scan_documentation(tmp_path) == []


def test_scan_documentation_reports_decode_and_read_errors_then_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    forbidden = chr(0xB7)
    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"\xff\xfe")
    unreadable = tmp_path / "unreadable.md"
    unreadable.write_text("content", encoding="utf-8")
    valid = tmp_path / "valid.md"
    valid.write_text(forbidden, encoding="utf-8")
    original_read_text = Path.read_text

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == unreadable:
            raise OSError("permission denied")
        return original_read_text(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", read_text)

    diagnostics = check_docs.scan_documentation(tmp_path)

    assert [(item.path.name, item.kind) for item in diagnostics] == [
        ("invalid.md", "read-error"),
        ("unreadable.md", "read-error"),
        ("valid.md", "forbidden-character"),
    ]
    assert check_docs.main(tmp_path) == 1
    error_output = capsys.readouterr().err
    assert "invalid.md:" in error_output
    assert "unreadable.md:" in error_output
    assert "valid.md:1:" in error_output


def test_main_prints_paths_and_lines_and_returns_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "bad.md").write_text(f"one\n{chr(0xB7)}\n", encoding="utf-8")

    assert check_docs.main(tmp_path) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "bad.md:2:" in output.err


def test_clean_tree_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "README.md").write_text("clean\n", encoding="utf-8")

    assert check_docs.main(tmp_path) == 0
    assert capsys.readouterr().err == ""
