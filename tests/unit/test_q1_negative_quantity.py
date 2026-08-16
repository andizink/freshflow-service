"""Rule Q1 — ``recommended_quantity < 0`` is quarantined as ``negative_quantity``.

515 real rows say "order -5 pieces". Turning that into 0 or 5 would be
inventing data, so the row is excluded and reported (DATA_GUIDE.md §3.3).
"""

import pytest

from app.common.enums import DatasetKind, ReasonCode
from app.ingest.rules import process_row

from .conftest import RowFactory


@pytest.mark.parametrize("raw", ["-5", "-1", "-100", "-0000012"])
def test_q1_negative_recommendation_is_quarantined(
    recommendation_row: RowFactory, raw: str
) -> None:
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS, recommendation_row(recommended_quantity=raw), None
    )

    assert processed.values is None
    assert processed.reasons == (ReasonCode.NEGATIVE_QUANTITY,)


@pytest.mark.parametrize(("raw", "expected"), [("0", 0), ("18", 18), ("-0", 0), ("+7", 7)])
def test_q1_non_negative_recommendations_load(
    recommendation_row: RowFactory, raw: str, expected: int
) -> None:
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS, recommendation_row(recommended_quantity=raw), None
    )

    assert processed.reasons == ()
    assert processed.values is not None
    assert processed.values["recommended_quantity"] == expected


def test_q1_zero_is_a_legitimate_recommendation(recommendation_row: RowFactory) -> None:
    """2,403 real rows recommend ordering nothing — that is an answer, not a defect."""
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS, recommendation_row(recommended_quantity="0"), None
    )

    assert processed.values is not None
    assert processed.values["recommended_quantity"] == 0


@pytest.mark.parametrize("raw", ["12.0", "12.5", "abc", "1_2", "12 pieces", "1e2"])
def test_q1_non_integer_quantities_are_invalid_not_coerced(
    recommendation_row: RowFactory, raw: str
) -> None:
    """Unlike ``item_number`` (N2), float forms are rejected: profiling proved
    every valid ``recommended_quantity`` is a plain integer literal, so a
    decimal point signals an unknown producer rather than a known defect.
    """
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS, recommendation_row(recommended_quantity=raw), None
    )

    assert processed.values is None
    assert processed.reasons == (ReasonCode.INVALID_VALUE,)


def test_q1_missing_quantity_is_a_missing_field(recommendation_row: RowFactory) -> None:
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS, recommendation_row(recommended_quantity=""), None
    )

    assert processed.values is None
    assert processed.reasons == (ReasonCode.MISSING_FIELD,)


def test_q1_negative_quantity_combines_with_other_reasons(
    recommendation_row: RowFactory, catalog: frozenset[int]
) -> None:
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS,
        recommendation_row(item_number="9901", recommended_quantity="-5"),
        catalog,
    )

    assert processed.values is None
    assert set(processed.reasons) == {ReasonCode.UNKNOWN_ITEM, ReasonCode.NEGATIVE_QUANTITY}
