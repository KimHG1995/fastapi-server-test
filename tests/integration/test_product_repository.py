from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.products.models import Product
from app.modules.products.repository import ProductRepository
from app.modules.products.schemas import (
    ProductListQuery,
    ProductSortField,
    SortOrder,
)
from app.modules.users.models import User, UserRole

UNPERSISTED_CREATOR_ID = UUID("94a2f8c0-5eaf-44a2-8f14-9bcc253677e0")


async def _seed_products(
    session: AsyncSession,
    products: list[Product],
) -> None:
    creator = User(
        email="product-admin@example.com",
        password_hash="unused",  # noqa: S106
        display_name="Product Admin",
        role=UserRole.ADMIN,
    )
    session.add(creator)
    await session.flush()
    for product in products:
        product.created_by_id = creator.id
    session.add_all(products)
    await session.commit()


def _product(
    *,
    product_id: str,
    sku: str,
    name: str,
    price: int = 1000,
    active: bool = True,
    deleted_at: datetime | None = None,
    created_at: datetime | None = None,
) -> Product:
    values: dict[str, object] = {}
    if created_at is not None:
        values["created_at"] = created_at
        values["updated_at"] = created_at
    return Product(
        id=UUID(product_id),
        sku=sku,
        name=name,
        description=None,
        price_in_minor_units=price,
        currency="KRW",
        stock_quantity=10,
        is_active=active,
        created_by_id=UNPERSISTED_CREATOR_ID,
        deleted_at=deleted_at,
        **values,
    )


async def test_public_queries_exclude_inactive_and_deleted_products(
    db_session: AsyncSession,
) -> None:
    deleted_at = datetime.now(UTC)
    visible = _product(
        product_id="00000000-0000-0000-0000-000000000001",
        sku="VISIBLE",
        name="Visible",
    )
    inactive = _product(
        product_id="00000000-0000-0000-0000-000000000002",
        sku="INACTIVE",
        name="Inactive",
        active=False,
    )
    deleted = _product(
        product_id="00000000-0000-0000-0000-000000000003",
        sku="DELETED",
        name="Deleted",
        deleted_at=deleted_at,
    )
    await _seed_products(db_session, [visible, inactive, deleted])
    repository = ProductRepository(db_session)

    products, total = await repository.list_public(ProductListQuery())

    assert [product.id for product in products] == [visible.id]
    assert total == 1
    assert await repository.get_public_by_id(visible.id) is not None
    assert await repository.get_public_by_id(inactive.id) is None
    assert await repository.get_public_by_id(deleted.id) is None


@pytest.mark.parametrize(
    ("search", "expected_sku"),
    [
        ("mixed-sku", "MIXED-SKU"),
        ("python GUIDE", "NAME-MATCH"),
        ("100%_REAL", "100%_REAL"),
    ],
)
async def test_search_matches_sku_and_name_case_insensitively_and_escapes_wildcards(
    db_session: AsyncSession,
    search: str,
    expected_sku: str,
) -> None:
    products = [
        _product(
            product_id="00000000-0000-0000-0000-000000000010",
            sku="MIXED-SKU",
            name="Unrelated",
        ),
        _product(
            product_id="00000000-0000-0000-0000-000000000011",
            sku="NAME-MATCH",
            name="Python Guide",
        ),
        _product(
            product_id="00000000-0000-0000-0000-000000000012",
            sku="100%_REAL",
            name="Literal wildcard characters",
        ),
        _product(
            product_id="00000000-0000-0000-0000-000000000013",
            sku="100XXREAL",
            name="Must not match escaped wildcards",
        ),
    ]
    await _seed_products(db_session, products)

    results, total = await ProductRepository(db_session).list_public(ProductListQuery(query=search))

    assert [product.sku for product in results] == [expected_sku]
    assert total == 1


async def test_pagination_uses_exact_filtered_count_and_stable_id_tie_breaker(
    db_session: AsyncSession,
) -> None:
    products = [
        _product(
            product_id=f"00000000-0000-0000-0000-00000000010{number}",
            sku=f"SAME-{number}",
            name="Same",
        )
        for number in range(5)
    ]
    products.extend(
        [
            _product(
                product_id="00000000-0000-0000-0000-000000000200",
                sku="INACTIVE",
                name="Same",
                active=False,
            ),
            _product(
                product_id="00000000-0000-0000-0000-000000000201",
                sku="OTHER",
                name="Other",
            ),
        ]
    )
    await _seed_products(db_session, products)

    page, total = await ProductRepository(db_session).list_public(
        ProductListQuery(
            page=2,
            page_size=2,
            query="same",
            sort=ProductSortField.NAME,
            order=SortOrder.ASC,
        )
    )

    assert [product.id for product in page] == [
        UUID("00000000-0000-0000-0000-000000000102"),
        UUID("00000000-0000-0000-0000-000000000103"),
    ]
    assert total == 5


@pytest.mark.parametrize(
    ("sort_field", "expected_skus"),
    [
        (ProductSortField.SKU, ["A-SKU", "B-SKU", "C-SKU"]),
        (ProductSortField.NAME, ["B-SKU", "C-SKU", "A-SKU"]),
        (ProductSortField.PRICE_IN_MINOR_UNITS, ["C-SKU", "A-SKU", "B-SKU"]),
        (ProductSortField.CREATED_AT, ["A-SKU", "B-SKU", "C-SKU"]),
    ],
)
async def test_sort_enum_maps_to_known_orm_columns(
    db_session: AsyncSession,
    sort_field: ProductSortField,
    expected_skus: list[str],
) -> None:
    now = datetime.now(UTC)
    await _seed_products(
        db_session,
        [
            _product(
                product_id="00000000-0000-0000-0000-000000000301",
                sku="A-SKU",
                name="Zulu",
                price=200,
                created_at=now,
            ),
            _product(
                product_id="00000000-0000-0000-0000-000000000302",
                sku="B-SKU",
                name="Alpha",
                price=300,
                created_at=now + timedelta(seconds=1),
            ),
            _product(
                product_id="00000000-0000-0000-0000-000000000303",
                sku="C-SKU",
                name="Bravo",
                price=100,
                created_at=now + timedelta(seconds=2),
            ),
        ],
    )

    products, _ = await ProductRepository(db_session).list_public(
        ProductListQuery(sort=sort_field, order=SortOrder.ASC)
    )

    assert [product.sku for product in products] == expected_skus


async def test_update_and_soft_delete_mutate_without_physical_deletion(
    db_session: AsyncSession,
) -> None:
    product = _product(
        product_id="00000000-0000-0000-0000-000000000401",
        sku="IMMUTABLE-SKU",
        name="Original",
    )
    await _seed_products(db_session, [product])
    repository = ProductRepository(db_session)

    updated = await repository.update(
        product.id,
        {"name": "Updated", "price_in_minor_units": 5500},
    )
    assert updated is not None
    assert updated.name == "Updated"
    assert updated.sku == "IMMUTABLE-SKU"

    deleted_at = datetime.now(UTC)
    deleted = await repository.soft_delete(product.id, deleted_at)
    await db_session.commit()

    assert deleted is not None
    assert deleted.deleted_at == deleted_at
    assert await repository.get_public_by_id(product.id) is None
    stored = await db_session.scalar(select(Product).where(Product.id == product.id))
    assert stored is not None
    assert stored.deleted_at == deleted_at
    assert await repository.update(product.id, {"name": "Resurrected"}) is None
    assert await repository.soft_delete(product.id, datetime.now(UTC)) is None
