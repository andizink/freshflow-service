"""Rules N7 and Q4 — the natural key that identifies duplicate rows.

``key_for`` is the single definition of "same row" used for both outcomes:
identical payloads collapse silently and are counted (N7), differing
payloads become ``conflicting_duplicate`` (Q4). The cross-row bookkeeping
itself lives in :mod:`app.ingest.service`; what is tested here is the key
that makes it correct.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.common.enums import DatasetKind
from app.ingest.rules import key_for, process_row

from .conftest import RowFactory


@pytest.mark.parametrize(
    ("dataset", "values", "expected"),
    [
        (DatasetKind.ITEMS, {"item_number": 1001, "name": "x"}, (1001,)),
        (
            DatasetKind.INVENTORY,
            {"store_id": "store_a", "item_number": 1001, "day": date(2024, 1, 1), "quantity": 1},
            ("store_a", 1001, date(2024, 1, 1)),
        ),
        (
            DatasetKind.ORDERABLE_ITEMS,
            {
                "store_id": "store_a",
                "item_number": 1001,
                "ordering_day": date(2024, 1, 1),
                "delivery_day": date(2024, 1, 2),
            },
            ("store_a", 1001, date(2024, 1, 1)),
        ),
        (
            DatasetKind.ORDER_RECOMMENDATIONS,
            {
                "store_id": "store_a",
                "item_number": 1001,
                "ordering_day": date(2024, 1, 1),
                "recommended_quantity": 18,
            },
            ("store_a", 1001, date(2024, 1, 1)),
        ),
    ],
)
def test_n7_key_matches_each_unique_constraint(
    dataset: DatasetKind, values: dict[str, object], expected: tuple[object, ...]
) -> None:
    assert key_for(dataset, values) == expected


def test_n7_keys_are_hashable_and_usable_as_dict_keys() -> None:
    values = {"store_id": "store_a", "item_number": 1001, "day": date(2024, 1, 1)}

    seen = {key_for(DatasetKind.INVENTORY, values): 1}

    assert key_for(DatasetKind.INVENTORY, dict(values)) in seen


def test_n7_key_is_computed_on_normalized_values(inventory_row: RowFactory) -> None:
    """``" STORE_A "`` and ``store_a`` must not slip past as two different keys."""
    dirty = process_row(
        DatasetKind.INVENTORY,
        inventory_row(store_id=" STORE_A ", item_number="1001.0", day="01/01/2024"),
        None,
    )
    clean = process_row(DatasetKind.INVENTORY, inventory_row(), None)

    assert dirty.values is not None
    assert clean.values is not None
    assert key_for(DatasetKind.INVENTORY, dirty.values) == key_for(
        DatasetKind.INVENTORY, clean.values
    )


def test_n7_different_days_are_different_keys(inventory_row: RowFactory) -> None:
    first = process_row(DatasetKind.INVENTORY, inventory_row(day="2024-01-01"), None)
    second = process_row(DatasetKind.INVENTORY, inventory_row(day="2024-01-02"), None)

    assert first.values is not None
    assert second.values is not None
    assert key_for(DatasetKind.INVENTORY, first.values) != key_for(
        DatasetKind.INVENTORY, second.values
    )


def test_q4_key_ignores_payload_so_conflicts_are_detectable(inventory_row: RowFactory) -> None:
    """Same key + different payload is exactly what Q4 must be able to see."""
    first = process_row(DatasetKind.INVENTORY, inventory_row(quantity="16.4"), None)
    second = process_row(DatasetKind.INVENTORY, inventory_row(quantity="99.9"), None)

    assert first.values is not None
    assert second.values is not None
    assert key_for(DatasetKind.INVENTORY, first.values) == key_for(
        DatasetKind.INVENTORY, second.values
    )
    assert first.values["quantity"] == Decimal("16.4")
    assert second.values["quantity"] == Decimal("99.9")


def test_n7_delivery_day_is_not_part_of_the_key(orderable_row: RowFactory) -> None:
    """Two rows for one ordering day are duplicates even if delivery differs."""
    first = process_row(DatasetKind.ORDERABLE_ITEMS, orderable_row(delivery_day="2024-01-02"), None)
    second = process_row(
        DatasetKind.ORDERABLE_ITEMS, orderable_row(delivery_day="2024-01-03"), None
    )

    assert first.values is not None
    assert second.values is not None
    assert key_for(DatasetKind.ORDERABLE_ITEMS, first.values) == key_for(
        DatasetKind.ORDERABLE_ITEMS, second.values
    )
