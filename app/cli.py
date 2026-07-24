import argparse
import asyncio
import getpass
import sys
from collections.abc import Sequence

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.security import hash_password_async
from app.db.errors import get_constraint_name
from app.db.session import create_engine_and_sessionmaker
from app.modules.auth.schemas import RegisterRequest
from app.modules.users.models import User, UserRole


class AdminAlreadyExistsError(Exception):
    pass


EMAIL_UNIQUE_CONSTRAINT = "uq_users_email"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Administrative commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_admin = subparsers.add_parser("create-admin", help="Create an administrator")
    create_admin.add_argument("--email", required=True)
    create_admin.add_argument("--display-name", required=True)
    return parser


async def create_admin(email: str, display_name: str, password: str) -> User:
    payload = RegisterRequest(email=email, display_name=display_name, password=password)
    normalized_email = str(payload.email).strip().lower()
    engine, session_factory = create_engine_and_sessionmaker(get_settings())
    try:
        async with session_factory() as session:
            commit_started = False
            try:
                existing = await session.scalar(select(User).where(User.email == normalized_email))
                if existing is not None:
                    raise AdminAlreadyExistsError
                password_hash = await hash_password_async(payload.password)
                user = User(
                    email=normalized_email,
                    password_hash=password_hash,
                    display_name=payload.display_name,
                    role=UserRole.ADMIN,
                    is_active=True,
                )
                session.add(user)
                commit_started = True
                await session.commit()
                return user
            except IntegrityError as exc:
                await session.rollback()
                if commit_started and get_constraint_name(exc) == EMAIL_UNIQUE_CONSTRAINT:
                    raise AdminAlreadyExistsError from exc
                raise
            except Exception:
                await session.rollback()
                raise
    finally:
        await engine.dispose()


async def async_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command != "create-admin":
        parser.error("unsupported command")

    password = getpass.getpass("Password: ")
    try:
        user = await create_admin(arguments.email, arguments.display_name, password)
    except ValidationError:
        print("error: invalid email, display name, or password", file=sys.stderr)
        return 1
    except AdminAlreadyExistsError:
        print("error: an account with this email already exists", file=sys.stderr)
        return 1

    print(f"id={user.id} email={user.email}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
