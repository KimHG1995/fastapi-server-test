import html
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_CHARACTER = chr(0xB7)
REFERENCE_DEFINITION = re.compile(r"^[ ]{0,3}\[([^\]]+)\]:[ \t]*(.*)$")
REFERENCE_USAGE = re.compile(r"!?\[([^\]\n]+)\]\[([^\]\n]*)\]")
ATX_HEADING = re.compile(r"^[ ]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$")
HTML_ANCHOR = re.compile(r"""<(?:a|span)\s+[^>]*\b(?:id|name)=["']([^"']+)["'][^>]*>""", re.I)
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
    target: str | None = None


@dataclass(frozen=True)
class MarkdownLink:
    target: str | None
    line: int


@dataclass(frozen=True)
class ParsedMarkdown:
    links: tuple[MarkdownLink, ...]
    anchors: frozenset[str]


def _normalize_reference_label(label: str) -> str:
    return " ".join(label.split()).casefold()


def _mask_inline_code(line: str) -> str:
    masked = list(line)
    index = 0
    active_ticks = 0
    while index < len(line):
        if line[index] != "`":
            if active_ticks:
                masked[index] = " "
            index += 1
            continue

        end = index
        while end < len(line) and line[end] == "`":
            end += 1
        tick_count = end - index
        for position in range(index, end):
            masked[position] = " "
        if active_ticks == 0:
            active_ticks = tick_count
        elif active_ticks == tick_count:
            active_ticks = 0
        index = end
    return "".join(masked)


def _fence_marker(line: str) -> tuple[str, int] | None:
    stripped = line.lstrip()
    indentation = len(line) - len(stripped)
    if indentation > 3 or not stripped or stripped[0] not in {"`", "~"}:
        return None
    marker = stripped[0]
    length = len(stripped) - len(stripped.lstrip(marker))
    return (marker, length) if length >= 3 else None


def _reference_destination(remainder: str) -> str | None:
    text = remainder.lstrip()
    if not text:
        return None
    if text.startswith("<"):
        closing = text.find(">", 1)
        return None if closing < 0 else text[1:closing]

    destination: list[str] = []
    depth = 0
    escaped = False
    for character in text:
        if escaped:
            destination.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "(":
            depth += 1
            destination.append(character)
        elif character == ")":
            if depth == 0:
                break
            depth -= 1
            destination.append(character)
        elif character.isspace() and depth == 0:
            break
        else:
            destination.append(character)
    return "".join(destination) or None


def _has_link_label(line: str, closing_bracket: int) -> bool:
    index = closing_bracket - 1
    while index >= 0:
        if line[index] == "]" and (index == 0 or line[index - 1] != "\\"):
            return False
        if line[index] == "[" and (index == 0 or line[index - 1] != "\\"):
            return True
        index -= 1
    return False


def _inline_destination(line: str, start: int) -> tuple[str | None, int]:
    index = start
    while index < len(line) and line[index].isspace():
        index += 1
    if index >= len(line):
        return None, len(line)

    if line[index] == "<":
        closing = index + 1
        while closing < len(line):
            if line[closing] == ">" and line[closing - 1] != "\\":
                return line[index + 1 : closing], closing + 1
            closing += 1
        return None, len(line)

    destination: list[str] = []
    depth = 1
    escaped = False
    while index < len(line):
        character = line[index]
        if escaped:
            destination.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "(":
            depth += 1
            destination.append(character)
        elif character == ")":
            depth -= 1
            if depth == 0:
                return "".join(destination) or None, index + 1
            destination.append(character)
        elif character.isspace() and depth == 1:
            return "".join(destination) or None, index
        else:
            destination.append(character)
        index += 1
    return None, len(line)


def _inline_links(line: str, line_number: int) -> list[MarkdownLink]:
    links: list[MarkdownLink] = []
    index = 0
    while index < len(line) - 1:
        if (
            line[index] == "]"
            and line[index + 1] == "("
            and (index == 0 or line[index - 1] != "\\")
            and _has_link_label(line, index)
        ):
            target, end = _inline_destination(line, index + 2)
            if target is not None:
                links.append(MarkdownLink(target=target, line=line_number))
            index = max(end, index + 2)
        else:
            index += 1
    return links


def _slug_heading(heading: str) -> str:
    without_html = re.sub(r"<[^>]+>", "", heading)
    without_links = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", without_html)
    without_formatting = without_links.translate(str.maketrans("", "", "`*_~"))
    normalized = unicodedata.normalize("NFKC", html.unescape(without_formatting)).casefold()
    slug_characters = [
        character
        for character in normalized
        if character in {" ", "-", "_"} or unicodedata.category(character)[0] in {"L", "M", "N"}
    ]
    return re.sub(r"[\s-]+", "-", "".join(slug_characters)).strip("-")


def parse_markdown(contents: str) -> ParsedMarkdown:
    lines = contents.splitlines()
    visible_lines: list[tuple[int, str]] = []
    references: dict[str, str] = {}
    anchors: set[str] = set()
    anchor_counts: dict[str, int] = {}
    active_fence: tuple[str, int] | None = None

    for line_number, original_line in enumerate(lines, start=1):
        marker = _fence_marker(original_line)
        if active_fence is not None:
            if marker is not None and marker[0] == active_fence[0] and marker[1] >= active_fence[1]:
                active_fence = None
            continue
        if marker is not None:
            active_fence = marker
            continue

        masked_line = _mask_inline_code(original_line)
        visible_lines.append((line_number, masked_line))
        heading_match = ATX_HEADING.match(original_line)
        if heading_match is not None:
            base_anchor = _slug_heading(heading_match.group(1))
            if base_anchor:
                duplicate_index = anchor_counts.get(base_anchor, 0)
                anchor = base_anchor if duplicate_index == 0 else f"{base_anchor}-{duplicate_index}"
                anchor_counts[base_anchor] = duplicate_index + 1
                anchors.add(anchor)
        anchors.update(unquote(match).casefold() for match in HTML_ANCHOR.findall(original_line))

        definition_match = REFERENCE_DEFINITION.match(masked_line)
        if definition_match is not None:
            target = _reference_destination(definition_match.group(2))
            if target is not None:
                references[_normalize_reference_label(definition_match.group(1))] = target

    links: list[MarkdownLink] = []
    for line_number, line in visible_lines:
        if REFERENCE_DEFINITION.match(line) is not None:
            continue
        links.extend(_inline_links(line, line_number))
        for usage in REFERENCE_USAGE.finditer(line):
            label = usage.group(2) or usage.group(1)
            links.append(
                MarkdownLink(
                    target=references.get(_normalize_reference_label(label)),
                    line=line_number,
                )
            )

    return ParsedMarkdown(links=tuple(links), anchors=frozenset(anchors))


def _is_external_target(target: str) -> bool:
    stripped = target.strip()
    if stripped.startswith(("/", "//")):
        return True
    return re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", stripped) is not None


def validate_local_markdown_links(
    document: Path,
    contents: str,
    *,
    root: Path,
    parsed_cache: dict[Path, ParsedMarkdown] | None = None,
) -> list[Diagnostic]:
    cache = parsed_cache if parsed_cache is not None else {}
    parsed = cache.setdefault(document.resolve(), parse_markdown(contents))
    diagnostics: list[Diagnostic] = []
    root = root.resolve()

    for link in parsed.links:
        if link.target is None:
            diagnostics.append(
                Diagnostic(
                    path=document.resolve().relative_to(root),
                    line=link.line,
                    kind="broken-local-link",
                    target=None,
                )
            )
            continue

        target = html.unescape(link.target.strip())
        if not target or _is_external_target(target):
            continue
        raw_path, has_fragment, raw_fragment = target.partition("#")
        path_text = unquote(raw_path.split("?", maxsplit=1)[0])
        target_path = (document.parent / path_text).resolve() if path_text else document.resolve()
        try:
            target_path.relative_to(root)
        except ValueError:
            target_exists = False
        else:
            target_exists = target_path.exists()

        anchor_exists = True
        if target_exists and has_fragment and target_path.suffix.casefold() == ".md":
            try:
                target_contents = target_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                anchor_exists = False
            else:
                target_parsed = cache.setdefault(target_path, parse_markdown(target_contents))
                anchor_exists = unquote(raw_fragment).casefold() in target_parsed.anchors

        if not target_exists or not anchor_exists:
            diagnostics.append(
                Diagnostic(
                    path=document.resolve().relative_to(root),
                    line=link.line,
                    kind="broken-local-link",
                    target=link.target,
                )
            )
    return diagnostics


def scan_documentation(root: Path = REPOSITORY_ROOT) -> list[Diagnostic]:
    root = root.resolve()
    diagnostics: list[Diagnostic] = []
    parsed_cache: dict[Path, ParsedMarkdown] = {}
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
                validate_local_markdown_links(
                    path,
                    contents,
                    root=root,
                    parsed_cache=parsed_cache,
                )
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
        if diagnostic.target:
            message = f"{message}: {diagnostic.target}"
        print(f"{location}: {message}", file=sys.stderr)
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
