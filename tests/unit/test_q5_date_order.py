"""Rule Q5 — ``delivery_day < ordering_day`` is quarantined.

Goods arriving before they were ordered is physically impossible, so the row
is corrupt regardless of how well every individual cell parses.
"""

import pytest

from app.common.enums import DatasetKind, ReasonCode
from app.ingest.rules import process_row

from .conftest import RowFactory

DATED_DATASETS = {
    "orderable": DatasetKind.ORDERABLE_ITEMS,
    "recommendation": DatasetKind.ORDER_RECOMMENDATIONS,
}


@pytest.mark.parametrize("fixture_name", list(DATED_DATASETS))
@pytest.mark.parametrize(
    ("ordering_day", "delivery_day"),
    [
        ("2024-01-05", "2024-01-04"),
        ("2024-01-05", "2024-01-01"),
        ("2024-01-01", "2023-12-31"),
        ("05/01/2024", "04/01/2024"),
    ],
)
def test_q5_delivery_before_ordering_is_quarantined(
    request: pytest.FixtureRequest, fixture_name: str, ordering_day: str, delivery_day: str
) -> None:
    make_row: RowFactory = request.getfixturevalue(f"{fixture_name}_row")

    processed = process_row(
        DATED_DATASETS[fixture_name],
        make_row(ordering_day=ordering_day, delivery_day=delivery_day),
        None,
    )

    assert processed.values is None
    assert processed.reasons == (ReasonCode.INVALID_DATE_ORDER,)


@pytest.mark.parametrize("fixture_name", list(DATED_DATASETS))
@pytest.mark.parametrize(
    ("ordering_day", "delivery_day"),
    [
        ("2024-01-01", "2024-01-02"),
        ("2024-01-01", "2024-01-03"),
        ("2024-01-01", "2024-01-01"),
        ("31/12/2024", "2024-12-31"),
    ],
)
def test_q5_same_or_later_delivery_loads(
    request: pytest.FixtureRequest, fixture_name: str, ordering_day: str, delivery_day: str
) -> None:
    """Real deliveries are ordering day +1 or +2; same-day is not impossible."""
    make_row: RowFactory = request.getfixturevalue(f"{fixture_name}_row")

    processed = process_row(
        DATED_DATASETS[fixture_name],
        make_row(ordering_day=ordering_day, delivery_day=delivery_day),
        None,
    )

    assert processed.reasons == ()
    assert processed.values is not None


def test_q5_is_compared_after_format_normalization(recommendation_row: RowFactory) -> None:
    """A mixed-format pair must be compared as dates, never as strings."""
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS,
        recommendation_row(ordering_day="01/01/2024", delivery_day="2024-01-02"),
        None,
    )

    assert processed.reasons == ()
    assert processed.values is not None


@pytest.mark.parametrize("bad_date", ["", "not-a-date"])
def test_q5_is_skipped_when_a_date_did_not_parse(
    recommendation_row: RowFactory, bad_date: str
) -> None:
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS, recommendation_row(ordering_day=bad_date), None
    )

    assert processed.values is None
    assert ReasonCode.INVALID_DATE_ORDER not in processed.reasons


def test_q5_does_not_apply_to_single_date_datasets(inventory_row: RowFactory) -> None:
    """``inventory`` has one date column, so there is no ordering to violate."""
    processed = process_row(DatasetKind.INVENTORY, inventory_row(day="2024-01-01"), None)

    assert processed.reasons == ()
