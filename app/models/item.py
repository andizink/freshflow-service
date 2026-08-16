"""ORM model for the items catalog (PLAN.md §4.1)."""

from decimal import Decimal

from sqlalchemy import Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Item(Base):
    """A catalog item, keyed by its natural item number.

    Attributes:
        item_number: Natural primary key, the item's catalog number.
        name: Item display name (whitespace-stripped, N5).
        category: Canonicalized category name (N4).
        is_bio: Whether the item is a "bio" (organic) product.
        purchase_price: Wholesale purchase price.
        suggested_retail_price: Suggested retail price.
    """

    __tablename__ = "items"

    item_number: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    category: Mapped[str] = mapped_column()
    is_bio: Mapped[bool] = mapped_column()
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    suggested_retail_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
