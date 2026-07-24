from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.products.dependencies import require_admin
from app.modules.products.models import Product
from app.modules.products.repository import ProductRepository
from app.modules.products.schemas import (
    ProductCreate,
    ProductListQuery,
    ProductSortField,
    ProductUpdate,
    SortOrder,
)
from app.modules.products.service import ProductService
from app.modules.users.models import User, UserRole

CREATOR_ID = UUID("468b6e55-0da2-4db7-9459-203652781f87")
PRODUCT_ID = UUID("f3f35b70-dd75-4886-b55e-a771de4ebcaf")
POSTGRES_INTEGER_MAX = 2_147_483_647


class _DriverConstraintViolation(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__("driver constraint violation")
        self.constraint_name = constraint_name


def _integrity_error(constraint_name: str) -> IntegrityError:
    driver_error = _DriverConstraintViolation(constraint_name)
    adapter_error = RuntimeError("asyncpg adapter integrity error")
    adapter_error.__cause__ = driver_error
    return IntegrityError("insert", {}, adapter_error)


class _Session:
    def __init__(self) -> None:
        self.transaction_active = True
        self.commits = 0
        self.rollbacks = 0
        self.refreshed: list[Product] = []

    def begin(self) -> None:
        raise AssertionError("Product writes must reuse the request transaction")

    async def commit(self) -> None:
        self.transaction_active = False
        self.commits += 1

    async def rollback(self) -> None:
        self.transaction_active = False
        self.rollbacks += 1

    async def refresh(self, product: Product) -> None:
        self.refreshed.append(product)


class _ProductRepository:
    def __init__(
        self,
        *,
        product: Product | None = None,
        create_error: IntegrityError | None = None,
        existing_sku: Product | None = None,
    ) -> None:
        self.product = product
        self.create_error = create_error
        self.existing_sku = existing_sku
        self.created: list[Product] = []
        self.queried_skus: list[str] = []
        self.updated: list[tuple[UUID, dict[str, object]]] = []
        self.deleted: list[tuple[UUID, datetime]] = []
        self.list_queries: list[ProductListQuery] = []

    async def create(self, product: Product) -> Product:
        if self.create_error is not None:
            raise self.create_error
        self.created.append(product)
        now = datetime.now(UTC)
        product.id = PRODUCT_ID
        product.created_at = now
        product.updated_at = now
        self.product = product
        return product

    async def get_by_sku(self, sku: str) -> Product | None:
        self.queried_skus.append(sku)
        return self.existing_sku

    async def get_public_by_id(self, product_id: UUID) -> Product | None:
        assert product_id == PRODUCT_ID
        return self.product

    async def list_public(
        self,
        query: ProductListQuery,
    ) -> tuple[list[Product], int]:
        self.list_queries.append(query)
        products = [] if self.product is None else [self.product]
        return products, len(products)

    async def update(
        self,
        product_id: UUID,
        changes: dict[str, object],
    ) -> Product | None:
        self.updated.append((product_id, changes))
        if self.product is None or self.product.deleted_at is not None:
            return None
        for field, value in changes.items():
            setattr(self.product, field, value)
        self.product.updated_at = datetime.now(UTC)
        return self.product

    async def soft_delete(
        self,
        product_id: UUID,
        deleted_at: datetime,
    ) -> Product | None:
        self.deleted.append((product_id, deleted_at))
        if self.product is None or self.product.deleted_at is not None:
            return None
        self.product.deleted_at = deleted_at
        return self.product


def _product(*, deleted_at: datetime | None = None) -> Product:
    now = datetime.now(UTC)
    return Product(
        id=PRODUCT_ID,
        sku="BOOK-001",
        name="Async Python",
        description="A server programming guide",
        price_in_minor_units=2500,
        currency="KRW",
        stock_quantity=7,
        is_active=True,
        created_by_id=CREATOR_ID,
        created_at=now,
        updated_at=now,
        deleted_at=deleted_at,
    )


def _service(
    repository: _ProductRepository,
) -> tuple[ProductService, _Session]:
    session = _Session()
    return (
        ProductService(
            cast(AsyncSession, session),
            repository=cast(ProductRepository, repository),
        ),
        session,
    )


def _create_request(**overrides: object) -> ProductCreate:
    values: dict[str, object] = {
        "sku": " book-001 ",
        "name": " Async Python ",
        "description": "A server programming guide",
        "price_in_minor_units": 2500,
        "currency": "krw",
        "stock_quantity": 7,
        "is_active": True,
    }
    values.update(overrides)
    return ProductCreate.model_validate(values)


def test_product_create_normalizes_codes_and_rejects_extra_fields() -> None:
    request = _create_request()

    assert request.sku == "BOOK-001"
    assert request.name == "Async Python"
    assert request.currency == "KRW"

    with pytest.raises(ValidationError) as raised:
        ProductCreate.model_validate(
            {
                **request.model_dump(),
                "created_by_id": str(CREATOR_ID),
            }
        )

    assert raised.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price_in_minor_units", 12.5),
        ("price_in_minor_units", True),
        ("stock_quantity", 1.5),
        ("stock_quantity", False),
    ],
)
def test_product_create_requires_integer_minor_units_and_stock(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _create_request(**{field: value})


@pytest.mark.parametrize("field", ["price_in_minor_units", "stock_quantity"])
def test_product_create_enforces_postgresql_integer_max(field: str) -> None:
    boundary = _create_request(**{field: POSTGRES_INTEGER_MAX})

    assert getattr(boundary, field) == POSTGRES_INTEGER_MAX
    with pytest.raises(ValidationError):
        _create_request(**{field: POSTGRES_INTEGER_MAX + 1})


def test_product_update_rejects_empty_extra_and_immutable_sku() -> None:
    for values in ({}, {"sku": "CHANGED"}, {"unexpected": "value"}):
        with pytest.raises(ValidationError):
            ProductUpdate.model_validate(values)


@pytest.mark.parametrize(
    "field",
    [
        "name",
        "price_in_minor_units",
        "currency",
        "stock_quantity",
        "is_active",
    ],
)
def test_product_update_rejects_explicit_null_for_non_nullable_fields(
    field: str,
) -> None:
    with pytest.raises(ValidationError):
        ProductUpdate.model_validate({field: None})


def test_product_update_allows_explicit_null_description() -> None:
    request = ProductUpdate.model_validate({"description": None})

    assert request.model_fields_set == {"description"}
    assert request.description is None


@pytest.mark.parametrize("field", ["price_in_minor_units", "stock_quantity"])
def test_product_update_enforces_postgresql_integer_max(field: str) -> None:
    boundary = ProductUpdate.model_validate({field: POSTGRES_INTEGER_MAX})

    assert getattr(boundary, field) == POSTGRES_INTEGER_MAX
    with pytest.raises(ValidationError):
        ProductUpdate.model_validate({field: POSTGRES_INTEGER_MAX + 1})


async def test_create_maps_fields_and_returns_public_shape() -> None:
    repository = _ProductRepository()
    service, session = _service(repository)

    result = await service.create(_create_request(), CREATOR_ID)

    assert result.id == PRODUCT_ID
    assert result.sku == "BOOK-001"
    assert result.currency == "KRW"
    assert not hasattr(result, "created_by_id")
    assert repository.created[0].created_by_id == CREATOR_ID
    assert session.commits == 1
    assert session.refreshed == repository.created


async def test_create_prechecks_sku_against_soft_deleted_products() -> None:
    repository = _ProductRepository(existing_sku=_product(deleted_at=datetime.now(UTC)))
    service, session = _service(repository)

    with pytest.raises(AppError) as raised:
        await service.create(_create_request(), CREATOR_ID)

    assert raised.value.status_code == 409
    assert raised.value.code == "SKU_ALREADY_EXISTS"
    assert repository.queried_skus == ["BOOK-001"]
    assert repository.created == []
    assert session.rollbacks == 1


async def test_create_maps_duplicate_sku_race_to_conflict() -> None:
    service, session = _service(
        _ProductRepository(create_error=_integrity_error("uq_products_sku"))
    )

    with pytest.raises(AppError) as raised:
        await service.create(_create_request(), CREATOR_ID)

    assert raised.value.status_code == 409
    assert raised.value.code == "SKU_ALREADY_EXISTS"
    assert session.rollbacks == 1


async def test_create_propagates_non_sku_integrity_errors() -> None:
    integrity_error = _integrity_error("fk_products_created_by_id_users")
    service, session = _service(_ProductRepository(create_error=integrity_error))

    with pytest.raises(IntegrityError) as raised:
        await service.create(_create_request(), CREATOR_ID)

    assert raised.value is integrity_error
    assert session.rollbacks == 1


@pytest.mark.parametrize("product", [None, _product(deleted_at=datetime.now(UTC))])
async def test_get_public_maps_missing_or_deleted_product_to_not_found(
    product: Product | None,
) -> None:
    service, _ = _service(_ProductRepository(product=product))

    with pytest.raises(AppError) as raised:
        await service.get_public(PRODUCT_ID)

    assert raised.value.status_code == 404
    assert raised.value.code == "PRODUCT_NOT_FOUND"


async def test_list_public_returns_typed_items_and_exact_total() -> None:
    repository = _ProductRepository(product=_product())
    service, _ = _service(repository)
    query = ProductListQuery(
        page=2,
        page_size=5,
        query="python",
        sort=ProductSortField.NAME,
        order=SortOrder.ASC,
    )

    items, total = await service.list_public(query)

    assert [item.id for item in items] == [PRODUCT_ID]
    assert total == 1
    assert repository.list_queries == [query]


async def test_update_applies_only_explicit_fields_and_keeps_sku_immutable() -> None:
    product = _product()
    repository = _ProductRepository(product=product)
    service, session = _service(repository)

    result = await service.update(
        PRODUCT_ID,
        ProductUpdate.model_validate({"name": " Updated ", "description": None}),
    )

    assert result.name == "Updated"
    assert result.description is None
    assert result.sku == "BOOK-001"
    assert repository.updated == [(PRODUCT_ID, {"name": "Updated", "description": None})]
    assert session.refreshed == [product]


@pytest.mark.parametrize("operation", ["update", "delete"])
@pytest.mark.parametrize("product", [None, _product(deleted_at=datetime.now(UTC))])
async def test_mutations_map_missing_or_deleted_product_to_not_found(
    operation: str,
    product: Product | None,
) -> None:
    service, _ = _service(_ProductRepository(product=product))

    with pytest.raises(AppError) as raised:
        if operation == "update":
            await service.update(
                PRODUCT_ID,
                ProductUpdate.model_validate({"name": "Updated"}),
            )
        else:
            await service.delete(PRODUCT_ID)

    assert raised.value.status_code == 404
    assert raised.value.code == "PRODUCT_NOT_FOUND"


async def test_delete_uses_soft_delete_timestamp() -> None:
    product = _product()
    repository = _ProductRepository(product=product)
    service, session = _service(repository)

    await service.delete(PRODUCT_ID)

    assert len(repository.deleted) == 1
    assert repository.deleted[0][0] == PRODUCT_ID
    assert repository.deleted[0][1].tzinfo is UTC
    assert product.deleted_at == repository.deleted[0][1]
    assert session.commits == 1


@pytest.mark.parametrize(
    ("role", "allowed"),
    [(UserRole.USER, False), (UserRole.ADMIN, True)],
)
async def test_require_admin_enforces_role(
    role: UserRole,
    allowed: bool,
) -> None:
    now = datetime.now(UTC)
    user = User(
        id=CREATOR_ID,
        email="actor@example.com",
        password_hash="unused",  # noqa: S106
        display_name="Actor",
        role=role,
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    if allowed:
        assert await require_admin(user) is user
        return

    with pytest.raises(AppError) as raised:
        await require_admin(user)

    assert raised.value.status_code == 403
    assert raised.value.code == "FORBIDDEN"
