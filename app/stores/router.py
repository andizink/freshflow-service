"""Stores API routes (PLAN.md §3.3).

Row-count aggregation is simple enough (three ``GROUP BY`` queries, no
enrichment joins) to live directly in the router rather than warranting a
dedicated ``app/stores/service.py`` module — consistent with the repository
layout in PLAN.md §5, which lists only ``app/stores/router.py``.
"""

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.db import SessionDep
from app.models.inventory import InventoryRecord
from app.models.order_recommendation import OrderRecommendation
from app.models.orderable_item import OrderableItem
from app.schemas.stores import StoreInfo, StoresResponse

router = APIRouter(tags=["stores"])


def _row_counts_by_store(
    session: Session, store_id_column: InstrumentedAttribute[str]
) -> dict[str, int]:
    """Count rows per ``store_id`` for one per-store table.

    Args:
        session: The active database session.
        store_id_column: The ``store_id`` mapped column of the table to
            aggregate over.

    Returns:
        A mapping of normalized ``store_id`` to its row count in that table.
    """
    rows = session.execute(select(store_id_column, func.count()).group_by(store_id_column)).all()
    return {store_id: int(count) for store_id, count in rows}


@router.get("/stores", response_model=StoresResponse)
async def list_stores(session: SessionDep) -> StoresResponse:
    """List all known stores with their per-dataset row counts.

    A store is known if it has at least one row in any of the ``inventory``,
    ``orderable_items``, or ``order_recommendations`` tables. Results are
    sorted by ``store_id``.

    Args:
        session: Injected database session.

    Returns:
        The known stores and their row counts.
    """
    inventory_counts = _row_counts_by_store(session, InventoryRecord.store_id)
    orderable_counts = _row_counts_by_store(session, OrderableItem.store_id)
    recommendation_counts = _row_counts_by_store(session, OrderRecommendation.store_id)

    store_ids = set(inventory_counts) | set(orderable_counts) | set(recommendation_counts)

    stores = [
        StoreInfo(
            store_id=store_id,
            inventory_rows=inventory_counts.get(store_id, 0),
            recommendation_rows=recommendation_counts.get(store_id, 0),
            orderable_rows=orderable_counts.get(store_id, 0),
        )
        for store_id in sorted(store_ids)
    ]
    return StoresResponse(stores=stores)
