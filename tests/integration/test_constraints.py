from collections.abc import Callable

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def test_users_reject_duplicate_normalized_emails(
    db_session: AsyncSession,
) -> None:
    from app.modules.users.models import User

    first_user = User(
        email="person@example.com",
        password_hash="first-hash",  # noqa: S106
        display_name="First",
    )
    second_user = User(
        email="person@example.com",
        password_hash="second-hash",  # noqa: S106
        display_name="Second",
    )
    db_session.add_all([first_user, second_user])

    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_products_reject_duplicate_skus(db_session: AsyncSession) -> None:
    from app.modules.products.models import Product
    from app.modules.users.models import User, UserRole

    creator = User(
        email="admin@example.com",
        password_hash="hash",  # noqa: S106
        display_name="Admin",
        role=UserRole.ADMIN,
    )
    db_session.add(creator)
    await db_session.flush()
    db_session.add_all(
        [
            Product(
                sku="DUPLICATE-SKU",
                name="First",
                price_in_minor_units=100,
                currency="USD",
                stock_quantity=1,
                created_by_id=creator.id,
            ),
            Product(
                sku="DUPLICATE-SKU",
                name="Second",
                price_in_minor_units=200,
                currency="USD",
                stock_quantity=2,
                created_by_id=creator.id,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.parametrize(
    "invalid_value",
    [
        pytest.param(
            lambda Product, creator_id: Product(
                sku="NEGATIVE-PRICE",
                name="Negative price",
                price_in_minor_units=-1,
                currency="USD",
                stock_quantity=0,
                created_by_id=creator_id,
            ),
            id="negative-price",
        ),
        pytest.param(
            lambda Product, creator_id: Product(
                sku="NEGATIVE-STOCK",
                name="Negative stock",
                price_in_minor_units=0,
                currency="USD",
                stock_quantity=-1,
                created_by_id=creator_id,
            ),
            id="negative-stock",
        ),
    ],
)
async def test_products_reject_negative_values(
    db_session: AsyncSession,
    invalid_value: Callable[[type, object], object],
) -> None:
    from app.modules.products.models import Product
    from app.modules.users.models import User, UserRole

    creator = User(
        email="admin@example.com",
        password_hash="hash",  # noqa: S106
        display_name="Admin",
        role=UserRole.ADMIN,
    )
    db_session.add(creator)
    await db_session.flush()
    db_session.add(invalid_value(Product, creator.id))

    with pytest.raises(IntegrityError):
        await db_session.commit()
