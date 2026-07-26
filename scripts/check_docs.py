import html
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

from markdown_it import MarkdownIt
from markdown_it.token import Token

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_CHARACTER = chr(0xB7)
HTML_ANCHOR = re.compile(r"""<(?:a|span)\s+[^>]*\b(?:id|name)=["']([^"']+)["'][^>]*>""", re.I)
URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
MARKDOWN = MarkdownIt("commonmark", {"html": True})
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
    target: str
    line: int


@dataclass(frozen=True)
class ParsedMarkdown:
    links: tuple[MarkdownLink, ...]
    anchors: frozenset[str]


def _inline_text(token: Token) -> str:
    parts: list[str] = []
    for child in token.children or []:
        if child.type in {"text", "code_inline", "image"}:
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append(" ")
        elif child.type == "html_inline":
            parts.append(re.sub(r"<[^>]+>", "", child.content))
    return "".join(parts)


def _slug_heading(heading: str) -> str:
    normalized = unicodedata.normalize("NFKC", html.unescape(heading)).casefold().strip()
    slug_characters = [
        character
        for character in normalized
        if character in {" ", "-", "_"}
        or character.isspace()
        or unicodedata.category(character)[0] in {"L", "M", "N"}
    ]
    return re.sub(r"\s+", "-", "".join(slug_characters)).strip("-")


def _reserve_anchor(base_anchor: str, used_anchors: set[str]) -> str:
    candidate = base_anchor
    suffix = 0
    while candidate in used_anchors:
        suffix += 1
        candidate = f"{base_anchor}-{suffix}"
    used_anchors.add(candidate)
    return candidate


def _links_from_children(children: list[Token] | None, line: int) -> list[MarkdownLink]:
    links: list[MarkdownLink] = []
    for child in children or []:
        attribute = "src" if child.type == "image" else "href"
        if child.type not in {"image", "link_open"}:
            continue
        target = child.attrGet(attribute)
        if target is not None:
            links.append(MarkdownLink(target=str(target), line=line))
    return links


def _links_from_inline(
    token: Token,
    source_lines: list[str],
    environment: dict[str, Any],
) -> list[MarkdownLink]:
    first_line = token.map[0] + 1 if token.map is not None else 1
    links = _links_from_children(token.children, first_line)
    if token.map is None or token.map[1] - token.map[0] <= 1:
        return links

    line_candidates: list[MarkdownLink] = []
    for line_index in range(token.map[0], token.map[1]):
        for inline in MARKDOWN.parseInline(source_lines[line_index], environment):
            line_candidates.extend(_links_from_children(inline.children, line_index + 1))

    mapped: list[MarkdownLink] = []
    candidate_index = 0
    for link in links:
        while (
            candidate_index < len(line_candidates)
            and line_candidates[candidate_index].target != link.target
        ):
            candidate_index += 1
        if candidate_index < len(line_candidates):
            mapped.append(line_candidates[candidate_index])
            candidate_index += 1
        else:
            mapped.append(link)
    return mapped


def parse_markdown(contents: str) -> ParsedMarkdown:
    environment: dict[str, Any] = {}
    tokens = MARKDOWN.parse(contents, environment)
    source_lines = contents.splitlines()
    links: list[MarkdownLink] = []
    anchors: set[str] = set()

    for index, token in enumerate(tokens):
        if token.type == "inline":
            links.extend(_links_from_inline(token, source_lines, environment))
        if token.type == "heading_open" and index + 1 < len(tokens):
            inline = tokens[index + 1]
            if inline.type == "inline":
                base_anchor = _slug_heading(_inline_text(inline))
                if base_anchor:
                    _reserve_anchor(base_anchor, anchors)
        if token.type in {"html_block", "inline"}:
            html_sources = [token.content]
            if token.type == "inline":
                html_sources.extend(
                    child.content for child in token.children or [] if child.type == "html_inline"
                )
            for source in html_sources:
                anchors.update(unquote(match).casefold() for match in HTML_ANCHOR.findall(source))

    return ParsedMarkdown(links=tuple(links), anchors=frozenset(anchors))


def _is_external_target(target: str) -> bool:
    stripped = target.strip()
    return stripped.startswith("//") or URI_SCHEME.match(stripped) is not None


def _resolve_local_path(document: Path, raw_path: str, root: Path) -> Path:
    decoded_path = unquote(raw_path.split("?", maxsplit=1)[0])
    if not decoded_path:
        return document.resolve()
    if decoded_path.startswith("/"):
        return (root / decoded_path.lstrip("/")).resolve()
    return (document.parent / decoded_path).resolve()


def validate_local_markdown_links(
    document: Path,
    contents: str,
    *,
    root: Path,
    parsed_cache: dict[Path, ParsedMarkdown] | None = None,
) -> list[Diagnostic]:
    cache = parsed_cache if parsed_cache is not None else {}
    document = document.resolve()
    root = root.resolve()
    parsed = cache.setdefault(document, parse_markdown(contents))
    diagnostics: list[Diagnostic] = []

    for link in parsed.links:
        target = html.unescape(link.target.strip())
        if not target or _is_external_target(target):
            continue

        raw_path, has_fragment, raw_fragment = target.partition("#")
        target_path = _resolve_local_path(document, raw_path, root)
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
                    path=document.relative_to(root),
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
