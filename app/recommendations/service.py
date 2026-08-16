"""Recommendations query and enrichment logic (PLAN.md §3.2)."""

from datetime import date

from sqlalchemy.orm import Session

from app.schemas.recommendations import RecommendationsResponse


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
    raise NotImplementedError
