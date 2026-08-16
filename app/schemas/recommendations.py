"""Pydantic response models for the recommendations API (PLAN.md §3.2)."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class RecommendationItem(BaseModel):
    """One enriched order recommendation line item.

    Attributes:
        item_number: Catalog item number.
        item_name: Item display name, ``None`` if the item is unknown to
            the catalog.
        category: Category, preferring the orderable-window category when
            present, else the catalog category.
        is_bio: Whether the item is a "bio" (organic) product, ``None`` if
            unknown to the catalog.
        recommended_quantity: Recommended quantity to order.
        delivery_day: The day the resulting order is expected to arrive.
        current_inventory: Same-day on-hand quantity rounded half-up to the
            nearest integer, ``None`` if no inventory record exists.
        purchase_price: Purchase price, preferring the orderable-window
            price over the catalog price.
        suggested_retail_price: Suggested retail price, preferring the
            orderable-window price over the catalog price.
        orderable: Whether an orderable window exists for this
            store/item/ordering-day.
        tags: Tags from the orderable window, empty if none.
    """

    model_config = ConfigDict(frozen=True)

    item_number: int
    item_name: str | None
    category: str | None
    is_bio: bool | None
    recommended_quantity: int
    delivery_day: date
    current_inventory: int | None
    purchase_price: float | None
    suggested_retail_price: float | None
    orderable: bool
    tags: list[str]


class RecommendationsResponse(BaseModel):
    """Order recommendations for one store and ordering day.

    Attributes:
        store_id: Normalized store identifier.
        day: The ordering day queried.
        count: Number of recommendations returned.
        recommendations: The recommendation line items.
    """

    model_config = ConfigDict(frozen=True)

    store_id: str
    day: date
    count: int
    recommendations: list[RecommendationItem]
