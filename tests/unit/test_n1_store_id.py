"""Rule N1 — ``store_id`` normalization: strip then lowercase.

Every literal spelling variant below was measured in the real per-store
files (8 distinct spellings of two real stores).
"""

import pytest

from app.common.enums import DatasetKind, ReasonCode
from app.ingest.normalize import normalize_store_id
from app.ingest.rules import STORE_ID_CLEANED, process_row

from .conftest import RowFactory


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("store_a", "store_a"),
        (" STORE_A ", "store_a"),
        ("store_a ", "store_a"),
        (" store_a", "store_a"),
        ("STORE_A", "store_a"),
        ("store_b ", "store_b"),
        (" store_b", "store_b"),
        ("STORE_B", "store_b"),
        ("\tstore_a\n", "store_a"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_n1_normalizes_store_id(raw: str, expected: str) -> None:
    assert normalize_store_id(raw) == expected


def test_n1_all_real_variants_collapse_to_two_stores() -> None:
    variants = ["store_a", " store_a", "store_a ", "STORE_A", "store_b", " store_b", "STORE_B"]

    assert set(map(normalize_store_id, variants)) == {"store_a", "store_b"}


@pytest.mark.parametrize(
    ("raw", "counted"),
    [("store_a", 0), (" STORE_A ", 1), ("store_a ", 1), ("STORE_A", 1)],
)
def test_n1_counts_only_actual_repairs(inventory_row: RowFactory, raw: str, counted: int) -> None:
    processed = process_row(DatasetKind.INVENTORY, inventory_row(store_id=raw), None)

    assert processed.values is not None
    assert processed.values["store_id"] == "store_a"
    assert processed.normalizations.get(STORE_ID_CLEANED, 0) == counted


def test_n1_blank_store_id_is_a_missing_field(inventory_row: RowFactory) -> None:
    processed = process_row(DatasetKind.INVENTORY, inventory_row(store_id="   "), None)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.MISSING_FIELD,)
