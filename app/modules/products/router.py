from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import problem_responses
from app.core.responses import (
    ApiResponse,
    PaginatedResponse,
    build_page_response,
    build_response,
)
from app.db.session import get_session
from app.modules.products.dependencies import require_admin
from app.modules.products.schemas import (
    ProductCreate,
    ProductListQuery,
    ProductRead,
    ProductUpdate,
)
from app.modules.products.service import ProductService
from app.modules.users.models import User

router = APIRouter(prefix="/products", tags=["products"])


@router.get(
    "",
    response_model=PaginatedResponse[ProductRead],
    responses=problem_responses(422),
)
async def list_products(
    request: Request,
    query: Annotated[ProductListQuery, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaginatedResponse[ProductRead]:
    items, total = await ProductService(session).list_public(query)
    return build_page_response(
        request,
        items,
        page=query.page,
        page_size=query.page_size,
        total=total,
    )


@router.get(
    "/{product_id}",
    response_model=ApiResponse[ProductRead],
    responses=problem_responses(404, 422),
)
async def get_product(
    product_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiResponse[ProductRead]:
    product = await ProductService(session).get_public(product_id)
    return build_response(request, product)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[ProductRead],
    responses=problem_responses(401, 403, 409, 422),
)
async def create_product(
    request: Request,
    payload: ProductCreate,
    current_admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiResponse[ProductRead]:
    product = await ProductService(session).create(payload, current_admin.id)
    return build_response(request, product)


@router.patch(
    "/{product_id}",
    response_model=ApiResponse[ProductRead],
    responses=problem_responses(401, 403, 404, 422),
)
async def update_product(
    product_id: UUID,
    request: Request,
    payload: ProductUpdate,
    current_admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiResponse[ProductRead]:
    del current_admin
    product = await ProductService(session).update(product_id, payload)
    return build_response(request, product)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=problem_responses(401, 403, 404, 422),
)
async def delete_product(
    product_id: UUID,
    current_admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    del current_admin
    await ProductService(session).delete(product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
