"""ORM model for orderable item windows (PLAN.md §4.1)."""

from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Date, Index, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OrderableItem(Base):
    """A store/item/ordering-day window during which an item can be ordered.

    Attributes:
        id: Surrogate primary key.
        store_id: Normalized store identifier (N1).
        item_number: Catalog item number.
        ordering_day: The day an order would be placed.
        delivery_day: The day the order is expected to arrive.
        purchase_price: Window-specific purchase price (overrides catalog).
        suggested_retail_price: Window-specific suggested retail price
            (overrides catalog).
        profit_margin: Optional profit margin for this window.
        tags: Normalized, deduped, lowercased tag list (N4).
        category: Canonicalized category name (N4).
    """

    __tablename__ = "orderable_items"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "item_number", "ordering_day", name="uq_orderable_store_item_day"
        ),
        Index("ix_orderable_store_ordering_day", "store_id", "ordering_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[str] = mapped_column()
    item_number: Mapped[int] = mapped_column()
    ordering_day: Mapped[date] = mapped_column(Date)
    delivery_day: Mapped[date] = mapped_column(Date)
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    suggested_retail_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    profit_margin: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON)
    category: Mapped[str] = mapped_column()
