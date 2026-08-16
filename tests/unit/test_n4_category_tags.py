"""Rule N4 — category and tag canonicalization (casing, whitespace, dedupe).

Literal values are the ones measured in ``items.csv`` and
``orderable_items.csv``: ``FRUITS`` / ``fruits``, ``NEW`` / ``"new  "`` /
``ON_SALE``.
"""

import pytest

from app.common.enums import DatasetKind, ReasonCode
from app.ingest.normalize import normalize_category, normalize_tags
from app.ingest.rules import CASING_NORMALIZED, VALUE_WHITESPACE_STRIPPED, process_row

from .conftest import RowFactory


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Fruits", "Fruits"),
        ("fruits", "Fruits"),
        ("FRUITS", "Fruits"),
        ("  FRUITS", "Fruits"),
        ("Fruits ", "Fruits"),
        ("Vegetables", "Vegetables"),
        ("vegetables", "Vegetables"),
        ("VEGETABLES", "Vegetables"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_n4_normalizes_category(raw: str, expected: str) -> None:
    assert normalize_category(raw) == expected


def test_n4_all_real_category_variants_collapse_to_two_values() -> None:
    variants = ["Fruits", "fruits", "FRUITS", "Vegetables", "vegetables", "VEGETABLES"]

    assert set(map(normalize_category, variants)) == {"Fruits", "Vegetables"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", []),
        ("   ", []),
        ("new", ["new"]),
        ("new  ", ["new"]),
        ("NEW", ["new"]),
        ("NEW  ", ["new"]),
        ("ON_SALE", ["on_sale"]),
        ("on_sale  ", ["on_sale"]),
        ("price_change  ", ["price_change"]),
        ("PRICE_CHANGE", ["price_change"]),
        ("new,on_sale", ["new", "on_sale"]),
        ("new, NEW, ON_SALE", ["new", "on_sale"]),
        ("new,,on_sale", ["new", "on_sale"]),
        (",", []),
        ("on_sale,new", ["on_sale", "new"]),
    ],
)
def test_n4_normalizes_tags(raw: str, expected: list[str]) -> None:
    assert normalize_tags(raw) == expected


def test_n4_tag_order_is_first_occurrence() -> None:
    assert normalize_tags("on_sale, new, ON_SALE, new") == ["on_sale", "new"]


@pytest.mark.parametrize(
    ("raw", "expected_counts"),
    [
        ("Fruits", {}),
        ("FRUITS", {CASING_NORMALIZED: 1}),
        ("fruits", {CASING_NORMALIZED: 1}),
        ("Fruits ", {CASING_NORMALIZED: 1}),
    ],
)
def test_n4_counts_category_canonicalization_once(
    orderable_row: RowFactory, raw: str, expected_counts: dict[str, int]
) -> None:
    processed = process_row(DatasetKind.ORDERABLE_ITEMS, orderable_row(category=raw), None)

    assert processed.values is not None
    assert processed.values["category"] == "Fruits"
    assert processed.normalizations == expected_counts


@pytest.mark.parametrize(
    ("raw", "expected_tags", "expected_counts"),
    [
        ("", [], {}),
        ("new", ["new"], {}),
        ("new  ", ["new"], {VALUE_WHITESPACE_STRIPPED: 1}),
        ("NEW", ["new"], {CASING_NORMALIZED: 1}),
        ("NEW  ", ["new"], {VALUE_WHITESPACE_STRIPPED: 1, CASING_NORMALIZED: 1}),
        ("new,ON_SALE", ["new", "on_sale"], {CASING_NORMALIZED: 1}),
        ("NEW,ON_SALE", ["new", "on_sale"], {CASING_NORMALIZED: 2}),
        ("new,new", ["new"], {}),
    ],
)
def test_n4_counts_tag_repairs_per_tag(
    orderable_row: RowFactory,
    raw: str,
    expected_tags: list[str],
    expected_counts: dict[str, int],
) -> None:
    processed = process_row(DatasetKind.ORDERABLE_ITEMS, orderable_row(tags=raw), None)

    assert processed.values is not None
    assert processed.values["tags"] == expected_tags
    assert processed.normalizations == expected_counts


def test_n4_blank_category_is_a_missing_field(orderable_row: RowFactory) -> None:
    processed = process_row(DatasetKind.ORDERABLE_ITEMS, orderable_row(category="  "), None)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.MISSING_FIELD,)


def test_n4_tags_are_optional(orderable_row: RowFactory) -> None:
    """An empty tag cell is normal (23,973 of 25,200 real rows), never a defect."""
    processed = process_row(DatasetKind.ORDERABLE_ITEMS, orderable_row(tags=""), None)

    assert processed.values is not None
    assert processed.values["tags"] == []
    assert processed.reasons == ()


@pytest.mark.parametrize(("raw", "expected"), [("True", True), ("TRUE", True), ("false", False)])
def test_n4_is_bio_casing_is_normalized(items_row: RowFactory, raw: str, expected: bool) -> None:
    processed = process_row(DatasetKind.ITEMS, items_row(is_bio=raw), None)

    assert processed.values is not None
    assert processed.values["is_bio"] is expected
    canonical = "True" if expected else "False"
    assert processed.normalizations.get(CASING_NORMALIZED, 0) == (0 if raw == canonical else 1)
