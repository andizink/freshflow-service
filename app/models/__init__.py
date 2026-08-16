"""ORM models, one module per table (PLAN.md §4.1).

Importing this package registers every model on :class:`app.db.Base`'s
metadata, which is required before :func:`app.db.init_db` is called.
"""

from app.models.ingest_job import IngestJob
from app.models.inventory import InventoryRecord
from app.models.item import Item
from app.models.order_recommendation import OrderRecommendation
from app.models.orderable_item import OrderableItem
from app.models.quarantine_row import QuarantineRow

__all__ = [
    "IngestJob",
    "InventoryRecord",
    "Item",
    "OrderRecommendation",
    "OrderableItem",
    "QuarantineRow",
]
