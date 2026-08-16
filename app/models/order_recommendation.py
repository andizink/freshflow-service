"""ORM model for order recommendations (PLAN.md §4.1)."""

from datetime import date

from sqlalchemy import Date, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OrderRecommendation(Base):
    """A recommended order quantity for a store/item/ordering-day.

    Attributes:
        id: Surrogate primary key.
        store_id: Normalized store identifier (N1).
        item_number: Catalog item number.
        ordering_day: The day the recommendation applies to.
        delivery_day: The day the resulting order is expected to arrive.
        recommended_quantity: Recommended quantity to order (non-negative;
            negative values are quarantined per Q1).
    """

    __tablename__ = "order_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "item_number", "ordering_day", name="uq_recommendation_store_item_day"
        ),
        Index("ix_recommendation_store_ordering_day", "store_id", "ordering_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[str] = mapped_column()
    item_number: Mapped[int] = mapped_column()
    ordering_day: Mapped[date] = mapped_column(Date)
    delivery_day: Mapped[date] = mapped_column(Date)
    recommended_quantity: Mapped[int] = mapped_column()
