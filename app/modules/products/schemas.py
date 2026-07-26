from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

POSTGRES_INTEGER_MAX = 2_147_483_647
MAX_PRODUCT_PAGE = 10_000


class ProductSortField(StrEnum):
    CREATED_AT = "created_at"
    NAME = "name"
    PRICE_IN_MINOR_UNITS = "price_in_minor_units"
    SKU = "sku"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            to_upper=True,
            min_length=1,
            max_length=64,
        ),
    ]
    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]
    description: Annotated[str | None, StringConstraints(max_length=2000)] = None
    price_in_minor_units: int = Field(
        ge=0,
        le=POSTGRES_INTEGER_MAX,
        strict=True,
    )
    currency: Annotated[
        str,
        StringConstraints(to_upper=True, pattern=r"^[A-Z]{3}$"),
    ]
    stock_quantity: int = Field(
        ge=0,
        le=POSTGRES_INTEGER_MAX,
        strict=True,
    )
    is_active: bool = True

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ] = None
    description: Annotated[str | None, StringConstraints(max_length=2000)] = None
    price_in_minor_units: int | None = Field(
        default=None,
        ge=0,
        le=POSTGRES_INTEGER_MAX,
        strict=True,
    )
    currency: Annotated[
        str | None,
        StringConstraints(to_upper=True, pattern=r"^[A-Z]{3}$"),
    ] = None
    stock_quantity: int | None = Field(
        default=None,
        ge=0,
        le=POSTGRES_INTEGER_MAX,
        strict=True,
    )
    is_active: bool | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def reject_empty_update(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one product field must be provided.")
        non_nullable_fields = {
            "name",
            "price_in_minor_units",
            "currency",
            "stock_quantity",
            "is_active",
        }
        explicitly_null = sorted(
            field
            for field in self.model_fields_set & non_nullable_fields
            if getattr(self, field) is None
        )
        if explicitly_null:
            fields = ", ".join(explicitly_null)
            raise ValueError(f"Product fields cannot be null: {fields}.")
        return self


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku: str
    name: str
    description: str | None
    price_in_minor_units: int
    currency: str
    stock_quantity: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(
        default=1,
        ge=1,
        le=MAX_PRODUCT_PAGE,
        description="Page number, capped to prevent abusive deep offsets.",
    )
    page_size: int = Field(default=20, ge=1, le=100)
    query: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ] = None
    sort: ProductSortField = ProductSortField.CREATED_AT
    order: SortOrder = SortOrder.DESC
