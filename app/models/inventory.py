"""ORM model for daily inventory records (PLAN.md §4.1)."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InventoryRecord(Base):
    """A store's on-hand quantity of an item for a given day.

    ``quantity`` is stored exactly as parsed (N6): fractional pieces are
    real information for weight-based items and are never rounded in the
    database, only in the API's ``current_inventory`` field.

    Attributes:
        id: Surrogate primary key.
        store_id: Normalized store identifier (N1).
        item_number: Catalog item number.
        day: The inventory snapshot day.
        quantity: On-hand quantity, exact Decimal (N6).
    """

    __tablename__ = "inventory_records"
    __table_args__ = (
        UniqueConstraint("store_id", "item_number", "day", name="uq_inventory_store_item_day"),
        Index("ix_inventory_store_day", "store_id", "day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[str] = mapped_column()
    item_number: Mapped[int] = mapped_column()
    day: Mapped[date] = mapped_column(Date)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
