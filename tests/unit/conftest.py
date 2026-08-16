"""Row factories shared by the unit tests for normalization/quarantine rules.

Each fixture returns a callable that builds a *clean* raw row for one
dataset — exactly the shape :func:`app.ingest.parser.read_rows` yields —
with keyword overrides for the cell under test. Tests therefore state only
the defect they exercise, and a clean baseline row is never copy-pasted.
"""

from collections.abc import Callable

import pytest

RowFactory = Callable[..., dict[str, str]]


def _factory(base: dict[str, str]) -> RowFactory:
    """Build a row factory that copies ``base`` and applies overrides.

    Args:
        base: The clean baseline row.

    Returns:
        A callable taking ``**overrides`` and returning a fresh row dict.
    """

    def make(**overrides: str) -> dict[str, str]:
        row = dict(base)
        row.update(overrides)
        return row

    return make


@pytest.fixture
def items_row() -> RowFactory:
    """Return a factory for clean ``items`` rows."""
    return _factory(
        {
            "item_number": "1001",
            "name": "Organic Bananas",
            "category": "Fruits",
            "is_bio": "False",
            "purchase_price": "0.89",
            "suggested_retail_price": "1.49",
        }
    )


@pytest.fixture
def inventory_row() -> RowFactory:
    """Return a factory for clean ``inventory`` rows."""
    return _factory(
        {
            "store_id": "store_a",
            "item_number": "1001",
            "day": "2024-01-01",
            "quantity": "16",
        }
    )


@pytest.fixture
def orderable_row() -> RowFactory:
    """Return a factory for clean ``orderable-items`` rows."""
    return _factory(
        {
            "store_id": "store_a",
            "item_number": "1001",
            "ordering_day": "2024-01-01",
            "delivery_day": "2024-01-02",
            "purchase_price": "0.89",
            "suggested_retail_price": "1.49",
            "profit_margin": "0.4474",
            "tags": "",
            "category": "Fruits",
        }
    )


@pytest.fixture
def recommendation_row() -> RowFactory:
    """Return a factory for clean ``order-recommendations`` rows."""
    return _factory(
        {
            "store_id": "store_a",
            "item_number": "1001",
            "ordering_day": "2024-01-01",
            "delivery_day": "2024-01-02",
            "recommended_quantity": "18",
        }
    )


@pytest.fixture
def catalog() -> frozenset[int]:
    """Return a small item catalog for the Q2 unknown-item check."""
    return frozenset({1001, 1002, 1003})
