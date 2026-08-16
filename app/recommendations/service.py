"""Recommendations query and enrichment logic (PLAN.md §3.2).

Query strategy (documented per the "avoid N+1" requirement): the
recommendation rows for ``(store_id, day)`` are fetched first, then the
catalog, inventory, and orderable-window tables are each batch-loaded with a
single ``IN (item_number, ...)`` query scoped to the item numbers actually
present in that recommendation set, and joined in Python via dictionaries
keyed by ``item_number``. This is four queries total regardless of how many
recommendation rows there are (plus the up-front store-existence check),
rather than one query per row.
"""

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.normalize import normalize_store_id
from app.models.inventory import InventoryRecord
from app.models.item import Item
from app.models.order_recommendation import OrderRecommendation
from app.models.orderable_item import OrderableItem
from app.schemas.recommendations import RecommendationItem, RecommendationsResponse

logger = logging.getLogger(__name__)


class StoreNotFoundError(LookupError):
    """Raised when a query targets a ``store_id`` with no known records.

    Attributes:
        store_id: The (normalized) store identifier that was not found.
    """

    def __init__(self, store_id: str) -> None:
        """Initialize the error with the unknown store identifier.

        Args:
            store_id: The (normalized) store identifier that was not found.
        """
        self.store_id = store_id
        super().__init__(f"Unknown store_id: {store_id!r}")


def get_recommendations(session: Session, store_id: str, day: date) -> RecommendationsResponse:
    """Fetch enriched order recommendations for a store and ordering day.

    ``store_id`` is normalized via :func:`app.ingest.normalize.normalize_store_id`
    (N1) before lookup, so callers may pass case/whitespace variants.

    Enrichment per PLAN.md §3.2:
      * Catalog join on ``item_number`` -> ``item_name``, ``category``,
        ``is_bio`` (``None`` for each if the item is unknown to the
        catalog).
      * Same-day inventory join on ``(store_id, item_number, day=ordering_day)``
        -> ``current_inventory``, the stored exact quantity rounded
        half-up to the nearest integer (``None`` if no record exists).
      * Orderable-window join on ``(store_id, item_number, ordering_day)``
        -> ``orderable`` flag, ``tags``; when a window exists, its
        ``purchase_price``/``suggested_retail_price`` override the catalog
        values, and its ``category`` overrides the catalog category.

    Args:
        session: The active database session.
        store_id: The store identifier, in any case/whitespace variant.
        day: The ordering day to fetch recommendations for.

    Returns:
        The enriched recommendations response. An empty ``recommendations``
        list (not a 404) is returned for a known store with no
        recommendations on ``day``.

    Raises:
        StoreNotFoundError: If ``store_id`` (after normalization) has no
            records in any dataset.
    """
    normalized_store_id = normalize_store_id(store_id)

    if not _store_exists(session, normalized_store_id):
        raise StoreNotFoundError(normalized_store_id)

    recommendation_rows = (
        session.execute(
            select(OrderRecommendation)
            .where(
                OrderRecommendation.store_id == normalized_store_id,
                OrderRecommendation.ordering_day == day,
            )
            .order_by(OrderRecommendation.item_number)
        )
        .scalars()
        .all()
    )

    item_numbers = [row.item_number for row in recommendation_rows]

    items_by_number = {
        item.item_number: item
        for item in session.execute(
            select(Item).where(Item.item_number.in_(item_numbers))
        ).scalars()
    }
    inventory_by_number = {
        record.item_number: record
        for record in session.execute(
            select(InventoryRecord).where(
                InventoryRecord.store_id == normalized_store_id,
                InventoryRecord.item_number.in_(item_numbers),
                InventoryRecord.day == day,
            )
        ).scalars()
    }
    windows_by_number = {
        window.item_number: window
        for window in session.execute(
            select(OrderableItem).where(
                OrderableItem.store_id == normalized_store_id,
                OrderableItem.item_number.in_(item_numbers),
                OrderableItem.ordering_day == day,
            )
        ).scalars()
    }

    recommendations = [
        _enrich(
            row,
            items_by_number.get(row.item_number),
            inventory_by_number.get(row.item_number),
            windows_by_number.get(row.item_number),
        )
        for row in recommendation_rows
    ]

    return RecommendationsResponse(
        store_id=normalized_store_id,
        day=day,
        count=len(recommendations),
        recommendations=recommendations,
    )


def _store_exists(session: Session, store_id: str) -> bool:
    """Check whether ``store_id`` has at least one row in any per-store table.

    A store is "known" if the normalized ``store_id`` appears in any of
    ``inventory``, ``orderable_items``, or ``order_recommendations``.

    Args:
        session: The active database session.
        store_id: The already-normalized store identifier.

    Returns:
        ``True`` if any of the three per-store tables has a matching row.
    """
    return (
        session.execute(
            select(InventoryRecord.id).where(InventoryRecord.store_id == store_id).limit(1)
        ).first()
        is not None
        or session.execute(
            select(OrderableItem.id).where(OrderableItem.store_id == store_id).limit(1)
        ).first()
        is not None
        or session.execute(
            select(OrderRecommendation.id).where(OrderRecommendation.store_id == store_id).limit(1)
        ).first()
        is not None
    )


def _round_half_up(value: Decimal) -> int:
    """Round a :class:`~decimal.Decimal` to the nearest integer, half-up.

    Args:
        value: The exact quantity to round.

    Returns:
        The rounded integer value.
    """
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _enrich(
    recommendation: OrderRecommendation,
    item: Item | None,
    inventory_record: InventoryRecord | None,
    window: OrderableItem | None,
) -> RecommendationItem:
    """Build one enriched :class:`RecommendationItem` from its joined rows.

    Args:
        recommendation: The order recommendation row being enriched.
        item: The matching catalog item, if the item is known.
        inventory_record: The matching same-day inventory row, if present.
        window: The matching orderable-window row, if present.

    Returns:
        The enriched recommendation line item.
    """
    purchase_price: Decimal | None
    suggested_retail_price: Decimal | None
    category: str | None
    if window is not None:
        purchase_price = window.purchase_price
        suggested_retail_price = window.suggested_retail_price
        category = window.category
    elif item is not None:
        purchase_price = item.purchase_price
        suggested_retail_price = item.suggested_retail_price
        category = item.category
    else:
        purchase_price = None
        suggested_retail_price = None
        category = None

    return RecommendationItem(
        item_number=recommendation.item_number,
        item_name=item.name if item is not None else None,
        category=category,
        is_bio=item.is_bio if item is not None else None,
        recommended_quantity=recommendation.recommended_quantity,
        delivery_day=recommendation.delivery_day,
        current_inventory=(
            _round_half_up(inventory_record.quantity) if inventory_record is not None else None
        ),
        purchase_price=float(purchase_price) if purchase_price is not None else None,
        suggested_retail_price=(
            float(suggested_retail_price) if suggested_retail_price is not None else None
        ),
        orderable=window is not None,
        tags=list(window.tags) if window is not None else [],
    )
