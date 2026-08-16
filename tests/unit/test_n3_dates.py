"""Rule N3 — date parsing: ISO ``YYYY-MM-DD`` first, then day-first ``DD/MM/YYYY``.

Day-first is not a guess: ``23/01/2024`` and ``31/12/2024`` appear in
``inventory.csv`` (803 slash-formatted rows) and there is no 23rd or 31st
month, so month-first is refuted by the data itself (ADR-007).
"""

from datetime import date

import pytest

from app.common.enums import DatasetKind, ReasonCode
from app.ingest.normalize import parse_day
from app.ingest.rules import DATE_FORMAT_CONVERTED, VALUE_WHITESPACE_STRIPPED, process_row

from .conftest import RowFactory


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2024-01-23", date(2024, 1, 23)),
        ("2024-12-31", date(2024, 12, 31)),
        (" 2024-01-23 ", date(2024, 1, 23)),
        ("23/01/2024", date(2024, 1, 23)),
        ("31/12/2024", date(2024, 12, 31)),
        (" 23/01/2024 ", date(2024, 1, 23)),
        ("01/05/2024", date(2024, 5, 1)),
        ("2024-02-29", date(2024, 2, 29)),
    ],
)
def test_n3_parses_both_accepted_formats(raw: str, expected: date) -> None:
    assert parse_day(raw) == expected


def test_n3_slash_dates_are_day_first() -> None:
    """The ambiguous-looking case resolves the same way as the proving ones."""
    assert parse_day("01/05/2024") == date(2024, 5, 1)
    assert parse_day("23/01/2024").month == parse_day("2024-01-23").month


@pytest.mark.parametrize(
    ("raw", "note"),
    [
        ("", "empty"),
        ("   ", "blank"),
        ("2024-01-23T00:00:00", "datetime strings are not dates"),
        ("20240123", "ISO basic format is not the agreed contract"),
        ("2024-W01-1", "ISO week dates are not the agreed contract"),
        ("2024-1-3", "unpadded ISO"),
        ("13/13/2024", "no 13th month either way"),
        ("01/13/2024", "month-first is not accepted"),
        ("2024/01/23", "wrong separator order"),
        ("23-01-2024", "day-first with dashes"),
        ("not-a-date", "garbage"),
        ("2024-02-30", "not a real day"),
        ("2024-13-01", "not a real month"),
    ],
)
def test_n3_rejects_everything_else(raw: str, note: str) -> None:
    with pytest.raises(ValueError, match="date is not a valid"):
        parse_day(raw)


@pytest.mark.parametrize(
    ("raw", "expected_counts"),
    [
        ("2024-01-01", {}),
        ("01/01/2024", {DATE_FORMAT_CONVERTED: 1}),
        (" 2024-01-01 ", {VALUE_WHITESPACE_STRIPPED: 1}),
        (" 01/01/2024 ", {DATE_FORMAT_CONVERTED: 1, VALUE_WHITESPACE_STRIPPED: 1}),
    ],
)
def test_n3_counts_only_converted_dates(
    inventory_row: RowFactory, raw: str, expected_counts: dict[str, int]
) -> None:
    processed = process_row(DatasetKind.INVENTORY, inventory_row(day=raw), None)

    assert processed.values is not None
    assert processed.values["day"] == date(2024, 1, 1)
    assert processed.normalizations == expected_counts


def test_n3_unparseable_date_is_quarantined(inventory_row: RowFactory) -> None:
    processed = process_row(DatasetKind.INVENTORY, inventory_row(day="32/01/2024"), None)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.INVALID_VALUE,)


def test_n3_counts_each_converted_date_column(orderable_row: RowFactory) -> None:
    """Two slash dates in one row are two repairs, not one."""
    processed = process_row(
        DatasetKind.ORDERABLE_ITEMS,
        orderable_row(ordering_day="01/01/2024", delivery_day="02/01/2024"),
        None,
    )

    assert processed.values is not None
    assert processed.normalizations[DATE_FORMAT_CONVERTED] == 2
