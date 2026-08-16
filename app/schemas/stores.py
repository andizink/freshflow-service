"""Pydantic response models for the stores API (PLAN.md §3.3)."""

from pydantic import BaseModel, ConfigDict


class StoreInfo(BaseModel):
    """Row counts for one known store, across the per-store datasets.

    Attributes:
        store_id: Normalized store identifier.
        inventory_rows: Number of inventory records for this store.
        recommendation_rows: Number of order recommendation records for
            this store.
        orderable_rows: Number of orderable-item window records for this
            store.
    """

    model_config = ConfigDict(frozen=True)

    store_id: str
    inventory_rows: int
    recommendation_rows: int
    orderable_rows: int


class StoresResponse(BaseModel):
    """All known stores and their row counts.

    Attributes:
        stores: The list of known stores.
    """

    model_config = ConfigDict(frozen=True)

    stores: list[StoreInfo]
