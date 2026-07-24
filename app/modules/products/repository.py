from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.products.models import Product
from app.modules.products.schemas import (
    ProductListQuery,
    ProductSortField,
    SortOrder,
)

_SORT_COLUMNS: dict[ProductSortField, InstrumentedAttribute[Any]] = {
    ProductSortField.CREATED_AT: Product.created_at,
    ProductSortField.NAME: Product.name,
    ProductSortField.PRICE_IN_MINOR_UNITS: Product.price_in_minor_units,
    ProductSortField.SKU: Product.sku,
}
_UPDATABLE_FIELDS = frozenset(
    {
        "name",
        "description",
        "price_in_minor_units",
        "currency",
        "stock_quantity",
        "is_active",
    }
)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, product: Product) -> Product:
        self._session.add(product)
        await self._session.flush()
        return product

    async def get_public_by_id(self, product_id: UUID) -> Product | None:
        statement = select(Product).where(
            Product.id == product_id,
            Product.is_active.is_(True),
            Product.deleted_at.is_(None),
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_public(
        self,
        query: ProductListQuery,
    ) -> tuple[list[Product], int]:
        filters: list[ColumnElement[bool]] = [
            Product.is_active.is_(True),
            Product.deleted_at.is_(None),
        ]
        if query.query is not None:
            pattern = f"%{_escape_like(query.query)}%"
            filters.append(
                or_(
                    Product.sku.ilike(pattern, escape="\\"),
                    Product.name.ilike(pattern, escape="\\"),
                )
            )

        count_statement = select(func.count()).select_from(Product).where(*filters)
        total = await self._session.scalar(count_statement)

        sort_column = _SORT_COLUMNS[query.sort]
        sort_expression = sort_column.asc() if query.order is SortOrder.ASC else sort_column.desc()
        statement = (
            select(Product)
            .where(*filters)
            .order_by(sort_expression, Product.id.asc())
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        result = await self._session.scalars(statement)
        return list(result.all()), int(total or 0)

    async def update(
        self,
        product_id: UUID,
        changes: Mapping[str, object],
    ) -> Product | None:
        statement = (
            select(Product)
            .where(
                Product.id == product_id,
                Product.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        product = await self._session.scalar(statement)
        if product is None:
            return None

        for field, value in changes.items():
            if field not in _UPDATABLE_FIELDS:
                raise ValueError(f"Product field is not updatable: {field}")
            setattr(product, field, value)
        await self._session.flush()
        return product

    async def soft_delete(
        self,
        product_id: UUID,
        deleted_at: datetime,
    ) -> Product | None:
        statement = (
            select(Product)
            .where(
                Product.id == product_id,
                Product.deleted_at.is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        product = await self._session.scalar(statement)
        if product is None:
            return None
        product.deleted_at = deleted_at
        await self._session.flush()
        return product
