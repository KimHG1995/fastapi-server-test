from typing import cast

from sqlalchemy import PrimaryKeyConstraint

from app.db.base import Base
from app.modules.auth.models import RefreshToken
from app.modules.products.models import Product
from app.modules.users.models import User


def test_orm_primary_key_names_match_baseline_migration() -> None:
    users_primary_key = cast(PrimaryKeyConstraint, User.__table__.primary_key)
    refresh_tokens_primary_key = cast(
        PrimaryKeyConstraint,
        RefreshToken.__table__.primary_key,
    )
    products_primary_key = cast(PrimaryKeyConstraint, Product.__table__.primary_key)

    assert users_primary_key.name == "pk_users"
    assert refresh_tokens_primary_key.name == "pk_refresh_tokens"
    assert products_primary_key.name == "pk_products"
    assert set(Base.metadata.tables) == {"users", "refresh_tokens", "products"}
