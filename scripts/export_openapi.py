import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the FastAPI OpenAPI document")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path, defaults to openapi/openapi.json in the repository",
    )
    return parser.parse_args()


def main(output: Path | None = None) -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://openapi:openapi@localhost/openapi",
        JWT_SECRET="x" * 32,
    )
    document = create_app(settings).openapi()
    target = output or REPOSITORY_ROOT / "openapi" / "openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main(_parse_args().output)
