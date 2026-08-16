"""Rule Q3 — unparseable values and empty required fields are quarantined.

Q3 splits into two reason codes: ``missing_field`` (the cell is empty, so
there is nothing to interpret) and ``invalid_value`` (the cell has content
that no rule can interpret). Both mean "we cannot repair what we cannot
read" (DATA_GUIDE.md §3.3).
"""

import pytest

from app.common.enums import DatasetKind, ReasonCode
from app.ingest.rules import process_row

from .conftest import RowFactory

REQUIRED_COLUMNS = {
    "items": ["item_number", "name", "category", "is_bio", "purchase_price"],
    "inventory": ["store_id", "item_number", "day", "quantity"],
    "orderable": [
        "store_id",
        "item_number",
        "ordering_day",
        "delivery_day",
        "purchase_price",
        "suggested_retail_price",
        "category",
    ],
    "recommendation": [
        "store_id",
        "item_number",
        "ordering_day",
        "delivery_day",
        "recommended_quantity",
    ],
}

DATASETS = {
    "items": DatasetKind.ITEMS,
    "inventory": DatasetKind.INVENTORY,
    "orderable": DatasetKind.ORDERABLE_ITEMS,
    "recommendation": DatasetKind.ORDER_RECOMMENDATIONS,
}


@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize(
    ("fixture_name", "column"),
    [(name, column) for name, columns in REQUIRED_COLUMNS.items() for column in columns],
)
def test_q3_every_required_column_reports_missing_field(
    request: pytest.FixtureRequest, fixture_name: str, column: str, blank: str
) -> None:
    make_row: RowFactory = request.getfixturevalue(f"{fixture_name}_row")

    processed = process_row(DATASETS[fixture_name], make_row(**{column: blank}), None)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.MISSING_FIELD,)


@pytest.mark.parametrize(
    ("column", "raw"),
    [
        ("item_number", "1001.5"),
        ("is_bio", "yes"),
        ("is_bio", "1"),
        ("purchase_price", "free"),
        ("purchase_price", "-0.89"),
        ("suggested_retail_price", "1,49"),
    ],
)
def test_q3_items_invalid_values_are_quarantined(
    items_row: RowFactory, column: str, raw: str
) -> None:
    processed = process_row(DatasetKind.ITEMS, items_row(**{column: raw}), None)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.INVALID_VALUE,)


def test_q3_negative_price_is_invalid(items_row: RowFactory) -> None:
    """A price below zero is corruption, not a discount."""
    processed = process_row(DatasetKind.ITEMS, items_row(purchase_price="-1.00"), None)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.INVALID_VALUE,)


def test_q3_optional_profit_margin_may_be_empty(orderable_row: RowFactory) -> None:
    """1,299 real rows have no margin; the column is nullable, so that is not a defect."""
    processed = process_row(DatasetKind.ORDERABLE_ITEMS, orderable_row(profit_margin=""), None)

    assert processed.reasons == ()
    assert processed.values is not None
    assert processed.values["profit_margin"] is None


def test_q3_missing_orderable_price_is_still_a_missing_field(
    orderable_row: RowFactory,
) -> None:
    """``purchase_price`` is non-nullable in the ORM, so a blank cell cannot load."""
    processed = process_row(DatasetKind.ORDERABLE_ITEMS, orderable_row(purchase_price=""), None)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.MISSING_FIELD,)


def test_q3_unparseable_profit_margin_is_invalid(orderable_row: RowFactory) -> None:
    processed = process_row(
        DatasetKind.ORDERABLE_ITEMS, orderable_row(profit_margin="forty percent"), None
    )

    assert processed.values is None
    assert processed.reasons == (ReasonCode.INVALID_VALUE,)


def test_q3_negative_profit_margin_is_allowed(orderable_row: RowFactory) -> None:
    """A negative margin is a loss-leader, not corrupt data."""
    processed = process_row(DatasetKind.ORDERABLE_ITEMS, orderable_row(profit_margin="-0.1"), None)

    assert processed.reasons == ()


def test_q3_reports_every_applicable_reason_not_just_the_first(
    recommendation_row: RowFactory, catalog: frozenset[int]
) -> None:
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS,
        recommendation_row(
            item_number="9901",
            ordering_day="2024-01-05",
            delivery_day="2024-01-04",
            recommended_quantity="-5",
        ),
        catalog,
    )

    assert processed.values is None
    assert set(processed.reasons) == {
        ReasonCode.UNKNOWN_ITEM,
        ReasonCode.INVALID_DATE_ORDER,
        ReasonCode.NEGATIVE_QUANTITY,
    }


def test_q3_repeated_reason_codes_are_deduplicated(items_row: RowFactory) -> None:
    """Three empty columns are still one ``missing_field`` row in the report."""
    processed = process_row(DatasetKind.ITEMS, items_row(name="", category="", is_bio=""), None)

    assert processed.reasons == (ReasonCode.MISSING_FIELD,)


def test_q3_mixed_missing_and_invalid_reports_both(inventory_row: RowFactory) -> None:
    processed = process_row(DatasetKind.INVENTORY, inventory_row(day="", quantity="abc"), None)

    assert set(processed.reasons) == {ReasonCode.MISSING_FIELD, ReasonCode.INVALID_VALUE}


def test_q3_absent_column_is_treated_as_missing() -> None:
    """Defensive: a row dict lacking a column behaves like an empty cell."""
    processed = process_row(DatasetKind.INVENTORY, {}, None)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.MISSING_FIELD,)
