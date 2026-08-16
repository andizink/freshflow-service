"""End-to-end ``process_row`` behavior per dataset: clean, dirty, and rejected rows.

Where the per-rule modules (``test_n*``/``test_q*``) pin one rule at a time,
this module pins the *contract* of the whole function: the exact keys and
types handed to the ORM, and the counting policy the ingest report depends
on.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.common.enums import DatasetKind, ReasonCode
from app.ingest.rules import (
    CASING_NORMALIZED,
    DATE_FORMAT_CONVERTED,
    ITEM_NUMBER_FLOAT_COERCED,
    NORMALIZATION_KEYS,
    STORE_ID_CLEANED,
    VALUE_WHITESPACE_STRIPPED,
    process_row,
)

from .conftest import RowFactory


def test_clean_items_row_maps_to_orm_columns(items_row: RowFactory) -> None:
    processed = process_row(DatasetKind.ITEMS, items_row(), None)

    assert processed.values == {
        "item_number": 1001,
        "name": "Organic Bananas",
        "category": "Fruits",
        "is_bio": False,
        "purchase_price": Decimal("0.89"),
        "suggested_retail_price": Decimal("1.49"),
    }
    assert processed.reasons == ()
    assert processed.normalizations == {}
    assert processed.warnings == {}


def test_clean_inventory_row_maps_to_orm_columns(inventory_row: RowFactory) -> None:
    processed = process_row(DatasetKind.INVENTORY, inventory_row(), None)

    assert processed.values == {
        "store_id": "store_a",
        "item_number": 1001,
        "day": date(2024, 1, 1),
        "quantity": Decimal("16"),
    }


def test_clean_orderable_row_maps_to_orm_columns(orderable_row: RowFactory) -> None:
    processed = process_row(DatasetKind.ORDERABLE_ITEMS, orderable_row(tags="new"), None)

    assert processed.values == {
        "store_id": "store_a",
        "item_number": 1001,
        "ordering_day": date(2024, 1, 1),
        "delivery_day": date(2024, 1, 2),
        "purchase_price": Decimal("0.89"),
        "suggested_retail_price": Decimal("1.49"),
        "profit_margin": Decimal("0.4474"),
        "tags": ["new"],
        "category": "Fruits",
    }


def test_clean_recommendation_row_maps_to_orm_columns(recommendation_row: RowFactory) -> None:
    processed = process_row(DatasetKind.ORDER_RECOMMENDATIONS, recommendation_row(), None)

    assert processed.values == {
        "store_id": "store_a",
        "item_number": 1001,
        "ordering_day": date(2024, 1, 1),
        "delivery_day": date(2024, 1, 2),
        "recommended_quantity": 18,
    }


def test_maximally_dirty_but_repairable_row_loads(inventory_row: RowFactory) -> None:
    """Every defect here has exactly one reasonable reading, so nothing is lost."""
    processed = process_row(
        DatasetKind.INVENTORY,
        inventory_row(
            store_id=" STORE_A ", item_number="1001.0", day="23/01/2024", quantity="16.4"
        ),
        frozenset({1001}),
    )

    assert processed.reasons == ()
    assert processed.values == {
        "store_id": "store_a",
        "item_number": 1001,
        "day": date(2024, 1, 23),
        "quantity": Decimal("16.4"),
    }
    assert processed.normalizations == {
        STORE_ID_CLEANED: 1,
        ITEM_NUMBER_FLOAT_COERCED: 1,
        DATE_FORMAT_CONVERTED: 1,
    }
    assert processed.warnings == {"fractional_quantity": 1}


def test_dirty_orderable_row_counts_every_repair(orderable_row: RowFactory) -> None:
    processed = process_row(
        DatasetKind.ORDERABLE_ITEMS,
        orderable_row(
            store_id="STORE_B",
            item_number=" 1002 ",
            category="FRUITS",
            tags="NEW  , on_sale",  # both tokens padded: 2 of the 4 strips
            profit_margin=" 0.5 ",
        ),
        None,
    )

    assert processed.reasons == ()
    assert processed.normalizations == {
        STORE_ID_CLEANED: 1,
        VALUE_WHITESPACE_STRIPPED: 4,
        CASING_NORMALIZED: 2,
    }


@pytest.mark.parametrize("name", NORMALIZATION_KEYS)
def test_normalization_keys_are_the_reported_vocabulary(name: str) -> None:
    """The report's fixed key set (PLAN.md §3.1) is defined in one place."""
    assert name in {
        STORE_ID_CLEANED,
        ITEM_NUMBER_FLOAT_COERCED,
        DATE_FORMAT_CONVERTED,
        VALUE_WHITESPACE_STRIPPED,
        CASING_NORMALIZED,
    }


def test_quarantined_row_reports_no_normalizations(inventory_row: RowFactory) -> None:
    """Report normalizations describe loaded rows only, so totals reconcile with the data."""
    processed = process_row(
        DatasetKind.INVENTORY,
        inventory_row(store_id=" STORE_A ", item_number="1001.0", day="oops"),
        None,
    )

    assert processed.values is None
    assert processed.normalizations == {}
    assert processed.warnings == {}


def test_quarantined_row_never_carries_values(items_row: RowFactory) -> None:
    processed = process_row(DatasetKind.ITEMS, items_row(is_bio="maybe"), None)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.INVALID_VALUE,)


def test_processed_row_is_frozen(items_row: RowFactory) -> None:
    processed = process_row(DatasetKind.ITEMS, items_row(), None)

    with pytest.raises(AttributeError):
        processed.values = None  # type: ignore[misc]


def test_processing_does_not_mutate_the_raw_row(inventory_row: RowFactory) -> None:
    """The raw row is what gets persisted to quarantine; it must stay original."""
    raw = inventory_row(store_id=" STORE_A ", quantity="16.4")
    original = dict(raw)

    process_row(DatasetKind.INVENTORY, raw, None)

    assert raw == original


@pytest.mark.parametrize("dataset", list(DatasetKind))
def test_every_dataset_is_processable(request: pytest.FixtureRequest, dataset: DatasetKind) -> None:
    fixtures = {
        DatasetKind.ITEMS: "items_row",
        DatasetKind.INVENTORY: "inventory_row",
        DatasetKind.ORDERABLE_ITEMS: "orderable_row",
        DatasetKind.ORDER_RECOMMENDATIONS: "recommendation_row",
    }
    make_row: RowFactory = request.getfixturevalue(fixtures[dataset])

    processed = process_row(dataset, make_row(), None)

    assert processed.values is not None
    assert processed.reasons == ()
