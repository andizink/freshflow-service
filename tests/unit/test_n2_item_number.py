"""Rule N2 — ``item_number`` coercion from float-formatted strings.

``"1001.0"`` (measured ~650 times in ``order_recommendations.csv``) is
repaired; ``"1001.5"`` is not, because guessing between 1001 and 1002 would
attach data to the wrong product (DATA_GUIDE.md §3.1).
"""

import pytest

from app.common.enums import DatasetKind, ReasonCode
from app.ingest.normalize import coerce_item_number
from app.ingest.rules import ITEM_NUMBER_FLOAT_COERCED, VALUE_WHITESPACE_STRIPPED, process_row

from .conftest import RowFactory


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1001", 1001),
        ("1001.0", 1001),
        ("1001.00", 1001),
        (" 1001 ", 1001),
        (" 1001.0 ", 1001),
        ("9903", 9903),
        ("0", 0),
        ("+1001", 1001),
        ("1e3", 1000),
        ("1001.", 1001),
    ],
)
def test_n2_coerces_zero_fractional_values(raw: str, expected: int) -> None:
    assert coerce_item_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "1001.5",
        "1000.9999",
        "abc",
        "",
        "   ",
        "1001,0",
        "nan",
        "Infinity",
        "1_2",
        "1001.0.0",
    ],
)
def test_n2_rejects_non_coercible_values(raw: str) -> None:
    with pytest.raises(ValueError, match="item_number"):
        coerce_item_number(raw)


def test_n2_preserves_sign_without_judging_plausibility() -> None:
    """N2 is a format rule; range/catalog validity is Q2's job, not N2's."""
    assert coerce_item_number("-5") == -5


@pytest.mark.parametrize(
    ("raw", "expected_counts"),
    [
        ("1001", {}),
        ("1001.0", {ITEM_NUMBER_FLOAT_COERCED: 1}),
        (" 1001 ", {VALUE_WHITESPACE_STRIPPED: 1}),
        (" 1001.0 ", {ITEM_NUMBER_FLOAT_COERCED: 1, VALUE_WHITESPACE_STRIPPED: 1}),
    ],
)
def test_n2_counts_float_coercion_and_stripping_separately(
    recommendation_row: RowFactory, raw: str, expected_counts: dict[str, int]
) -> None:
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS, recommendation_row(item_number=raw), None
    )

    assert processed.values is not None
    assert processed.values["item_number"] == 1001
    assert processed.normalizations == expected_counts


def test_n2_uncoercible_item_number_is_quarantined(recommendation_row: RowFactory) -> None:
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS, recommendation_row(item_number="1001.5"), None
    )

    assert processed.values is None
    assert processed.reasons == (ReasonCode.INVALID_VALUE,)


def test_n2_missing_item_number_is_a_missing_field(recommendation_row: RowFactory) -> None:
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS, recommendation_row(item_number=""), None
    )

    assert processed.values is None
    assert processed.reasons == (ReasonCode.MISSING_FIELD,)
