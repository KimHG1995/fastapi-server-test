import pytest
from pydantic import ValidationError

from app.modules.products.schemas import ProductListQuery

PUBLIC_MAX_PRODUCT_PAGE = 10_000


def test_product_list_query_accepts_the_maximum_public_page() -> None:
    query = ProductListQuery(page=PUBLIC_MAX_PRODUCT_PAGE, page_size=100)

    assert query.page == PUBLIC_MAX_PRODUCT_PAGE


@pytest.mark.parametrize(
    "page",
    [PUBLIC_MAX_PRODUCT_PAGE + 1, 9_223_372_036_854_775_808],
)
def test_product_list_query_rejects_abusive_deep_pages(page: int) -> None:
    with pytest.raises(ValidationError):
        ProductListQuery(page=page)
