import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_CHARACTER = chr(0xB7)


def find_violations(root: Path = REPOSITORY_ROOT) -> list[tuple[Path, int]]:
    violations: list[tuple[Path, int]] = []
    for path in sorted(root.rglob("*.md")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if FORBIDDEN_CHARACTER in line:
                violations.append((path.relative_to(root), line_number))
    return violations


def main() -> int:
    violations = find_violations()
    for path, line_number in violations:
        print(f"{path}:{line_number}: forbidden documentation character", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
