from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.products.models import Product
from app.modules.products.repository import ProductRepository
from app.modules.products.schemas import (
    ProductCreate,
    ProductListQuery,
    ProductRead,
    ProductUpdate,
)

SKU_UNIQUE_CONSTRAINT = "uq_products_sku"


def _constraint_name(error: IntegrityError) -> str | None:
    pending: list[BaseException] = [error.orig] if isinstance(error.orig, BaseException) else []
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in visited:
            continue
        visited.add(identity)

        constraint_name = getattr(current, "constraint_name", None)
        if isinstance(constraint_name, str):
            return constraint_name

        for linked_error in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if isinstance(linked_error, BaseException):
                pending.append(linked_error)
    return None


class SkuAlreadyExistsError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="SKU_ALREADY_EXISTS",
            status_code=409,
            title="Conflict",
            detail="A product with this SKU already exists.",
            type_slug="sku-already-exists",
        )


class ProductNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="PRODUCT_NOT_FOUND",
            status_code=404,
            title="Not Found",
            detail="Product was not found.",
            type_slug="product-not-found",
        )


class ProductService:
    def __init__(
        self,
        session: AsyncSession,
        repository: ProductRepository | None = None,
    ) -> None:
        self._session = session
        self._repository = repository or ProductRepository(session)

    async def create(
        self,
        request: ProductCreate,
        creator_id: UUID,
    ) -> ProductRead:
        product = Product(
            **request.model_dump(),
            created_by_id=creator_id,
        )
        try:
            if await self._repository.get_by_sku(request.sku) is not None:
                raise SkuAlreadyExistsError
            created = await self._repository.create(product)
            await self._session.refresh(created)
            result = ProductRead.model_validate(created)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _constraint_name(exc) == SKU_UNIQUE_CONSTRAINT:
                raise SkuAlreadyExistsError from exc
            raise
        except Exception:
            await self._session.rollback()
            raise
        return result

    async def get_public(self, product_id: UUID) -> ProductRead:
        product = await self._repository.get_public_by_id(product_id)
        return self._read_or_raise(product)

    async def list_public(
        self,
        query: ProductListQuery,
    ) -> tuple[list[ProductRead], int]:
        products, total = await self._repository.list_public(query)
        return ([ProductRead.model_validate(product) for product in products], total)

    async def update(
        self,
        product_id: UUID,
        request: ProductUpdate,
    ) -> ProductRead:
        changes = request.model_dump(exclude_unset=True)
        try:
            product = await self._repository.update(product_id, changes)
            product = self._model_or_raise(product)
            await self._session.refresh(product)
            result = ProductRead.model_validate(product)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return result

    async def delete(self, product_id: UUID) -> None:
        try:
            product = await self._repository.soft_delete(
                product_id,
                datetime.now(UTC),
            )
            if product is None:
                raise ProductNotFoundError
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    @staticmethod
    def _model_or_raise(product: Product | None) -> Product:
        if product is None or product.deleted_at is not None:
            raise ProductNotFoundError
        return product

    @classmethod
    def _read_or_raise(cls, product: Product | None) -> ProductRead:
        return ProductRead.model_validate(cls._model_or_raise(product))
