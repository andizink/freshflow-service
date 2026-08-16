"""Rule N6 — inventory quantities are parsed exactly and never rounded.

``16.4`` pieces contradicts the "all quantities are in pieces" README claim,
but 22,407 of 25,868 real rows are fractional: rounding at ingest would
destroy the original value forever, so the row loads exactly and the report
warns (ADR-008).
"""

from decimal import Decimal

import pytest

from app.common.enums import DatasetKind, ReasonCode
from app.ingest.normalize import parse_quantity
from app.ingest.rules import FRACTIONAL_QUANTITY, VALUE_WHITESPACE_STRIPPED, process_row

from .conftest import RowFactory


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("16.4", Decimal("16.4")),
        ("24.0", Decimal("24.0")),
        ("0", Decimal("0")),
        (" 16.4 ", Decimal("16.4")),
        ("23.7", Decimal("23.7")),
        ("-5", Decimal("-5")),
        ("1e2", Decimal("100")),
        ("0.001", Decimal("0.001")),
    ],
)
def test_n6_parses_decimal_quantities(raw: str, expected: Decimal) -> None:
    assert parse_quantity(raw) == expected


def test_n6_is_exact_not_binary_float() -> None:
    """The whole point of Decimal: 16.4 stays 16.4, bit for bit."""
    assert str(parse_quantity("16.4")) == "16.4"
    assert parse_quantity("16.4") * 3 == Decimal("49.2")


@pytest.mark.parametrize("raw", ["", "   ", "abc", "16,4", "nan", "NaN", "Infinity", "-inf"])
def test_n6_rejects_non_numeric_quantities(raw: str) -> None:
    with pytest.raises(ValueError, match="quantity is not a"):
        parse_quantity(raw)


@pytest.mark.parametrize(
    ("raw", "warned"),
    [("16", False), ("16.0", False), ("16.4", True), ("0.5", True), ("0", False)],
)
def test_n6_warns_only_on_fractional_quantities(
    inventory_row: RowFactory, raw: str, warned: bool
) -> None:
    processed = process_row(DatasetKind.INVENTORY, inventory_row(quantity=raw), None)

    assert processed.values is not None
    assert processed.values["quantity"] == Decimal(raw)
    assert processed.warnings == ({FRACTIONAL_QUANTITY: 1} if warned else {})


def test_n6_fractional_row_is_loaded_not_quarantined(inventory_row: RowFactory) -> None:
    processed = process_row(DatasetKind.INVENTORY, inventory_row(quantity="16.4"), None)

    assert processed.reasons == ()
    assert processed.values is not None


def test_n6_whitespace_around_quantity_is_stripped_and_counted(
    inventory_row: RowFactory,
) -> None:
    processed = process_row(DatasetKind.INVENTORY, inventory_row(quantity=" 16.4 "), None)

    assert processed.values is not None
    assert processed.normalizations == {VALUE_WHITESPACE_STRIPPED: 1}


@pytest.mark.parametrize("raw", ["abc", "16,4", "NaN"])
def test_n6_unparseable_quantity_is_quarantined(inventory_row: RowFactory, raw: str) -> None:
    processed = process_row(DatasetKind.INVENTORY, inventory_row(quantity=raw), None)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.INVALID_VALUE,)


def test_n6_negative_inventory_is_invalid_value_not_negative_quantity(
    inventory_row: RowFactory,
) -> None:
    """Q1 is scoped to ``recommended_quantity``; a negative stock count is corrupt data."""
    processed = process_row(DatasetKind.INVENTORY, inventory_row(quantity="-5"), None)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.INVALID_VALUE,)


def test_n6_quarantined_row_reports_no_warnings(inventory_row: RowFactory) -> None:
    """Warnings, like normalizations, describe loaded rows only."""
    processed = process_row(
        DatasetKind.INVENTORY, inventory_row(quantity="16.4", day="not-a-date"), None
    )

    assert processed.values is None
    assert processed.warnings == {}
