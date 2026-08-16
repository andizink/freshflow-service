"""Rule N5 — surrounding whitespace is stripped from text fields.

``"Cucumber  "``, ``"Eggplant  "``, ``"Celery Stalk  "`` and ``"Pak Choi  "``
are the four real ``items.csv`` names carrying trailing spaces.
"""

import pytest

from app.common.enums import DatasetKind, ReasonCode
from app.ingest.normalize import strip_text
from app.ingest.rules import VALUE_WHITESPACE_STRIPPED, process_row

from .conftest import RowFactory


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Organic Bananas", "Organic Bananas"),
        ("Cucumber  ", "Cucumber"),
        ("Eggplant  ", "Eggplant"),
        ("  Celery Stalk  ", "Celery Stalk"),
        ("\tPak Choi\n", "Pak Choi"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_n5_strips_surrounding_whitespace(raw: str, expected: str) -> None:
    assert strip_text(raw) == expected


def test_n5_preserves_inner_whitespace() -> None:
    """Only *surrounding* whitespace is noise; inner spacing is the value."""
    assert strip_text("  Grapes White Seedless  ") == "Grapes White Seedless"


@pytest.mark.parametrize(
    ("raw", "counted"),
    [("Cucumber", 0), ("Cucumber  ", 1), ("  Cucumber", 1)],
)
def test_n5_counts_only_actual_strips(items_row: RowFactory, raw: str, counted: int) -> None:
    processed = process_row(DatasetKind.ITEMS, items_row(name=raw), None)

    assert processed.values is not None
    assert processed.values["name"] == "Cucumber"
    assert processed.normalizations.get(VALUE_WHITESPACE_STRIPPED, 0) == counted


def test_n5_counts_each_stripped_column(items_row: RowFactory) -> None:
    processed = process_row(
        DatasetKind.ITEMS,
        items_row(name="Cucumber  ", purchase_price=" 0.89 ", suggested_retail_price="1.49 "),
        None,
    )

    assert processed.values is not None
    assert processed.normalizations[VALUE_WHITESPACE_STRIPPED] == 3


def test_n5_whitespace_only_name_is_a_missing_field(items_row: RowFactory) -> None:
    processed = process_row(DatasetKind.ITEMS, items_row(name="   "), None)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.MISSING_FIELD,)
