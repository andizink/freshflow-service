"""Rule Q2 — item numbers absent from the catalog are quarantined.

Items ``1099`` and ``9901``-``9903`` appear in the per-store files but not in
``items.csv``. Without a catalog entry there is no name, price, or category
to serve, so the row is excluded and stays recoverable by re-ingesting after
the catalog grows (DATA_GUIDE.md §3.3).
"""

import pytest

from app.common.enums import DatasetKind, ReasonCode
from app.ingest.rules import process_row

from .conftest import RowFactory

UNKNOWN_ITEMS = ["1099", "9901", "9902", "9903"]


@pytest.mark.parametrize("dataset_fixture", ["inventory", "orderable", "recommendation"])
@pytest.mark.parametrize("item_number", UNKNOWN_ITEMS)
def test_q2_unknown_item_is_quarantined_in_every_per_store_dataset(
    request: pytest.FixtureRequest,
    catalog: frozenset[int],
    dataset_fixture: str,
    item_number: str,
) -> None:
    datasets = {
        "inventory": DatasetKind.INVENTORY,
        "orderable": DatasetKind.ORDERABLE_ITEMS,
        "recommendation": DatasetKind.ORDER_RECOMMENDATIONS,
    }
    make_row: RowFactory = request.getfixturevalue(f"{dataset_fixture}_row")

    processed = process_row(datasets[dataset_fixture], make_row(item_number=item_number), catalog)

    assert processed.values is None
    assert processed.reasons == (ReasonCode.UNKNOWN_ITEM,)


def test_q2_known_item_loads(inventory_row: RowFactory, catalog: frozenset[int]) -> None:
    processed = process_row(DatasetKind.INVENTORY, inventory_row(item_number="1001"), catalog)

    assert processed.reasons == ()
    assert processed.values is not None


def test_q2_check_is_skipped_when_catalog_is_none(inventory_row: RowFactory) -> None:
    """``None`` means "do not check" — used for the ``items`` dataset itself."""
    processed = process_row(DatasetKind.INVENTORY, inventory_row(item_number="9901"), None)

    assert processed.reasons == ()
    assert processed.values is not None


def test_q2_empty_catalog_quarantines_everything(inventory_row: RowFactory) -> None:
    """Ingesting a per-store file before ``items`` is allowed but visible in the report."""
    processed = process_row(DatasetKind.INVENTORY, inventory_row(), frozenset())

    assert processed.values is None
    assert processed.reasons == (ReasonCode.UNKNOWN_ITEM,)


def test_q2_float_formatted_item_number_is_checked_after_coercion(
    recommendation_row: RowFactory, catalog: frozenset[int]
) -> None:
    """``"1001.0"`` is a known item; N2 runs before Q2, not after."""
    processed = process_row(
        DatasetKind.ORDER_RECOMMENDATIONS, recommendation_row(item_number="1001.0"), catalog
    )

    assert processed.reasons == ()
    assert processed.values is not None
    assert processed.values["item_number"] == 1001


@pytest.mark.parametrize("raw", ["", "1001.5", "abc"])
def test_q2_is_not_reported_for_unparseable_item_numbers(
    inventory_row: RowFactory, catalog: frozenset[int], raw: str
) -> None:
    """An unreadable number is one defect, not also an "unknown" item."""
    processed = process_row(DatasetKind.INVENTORY, inventory_row(item_number=raw), catalog)

    assert processed.values is None
    assert ReasonCode.UNKNOWN_ITEM not in processed.reasons


def test_q2_items_dataset_ignores_the_catalog(items_row: RowFactory) -> None:
    processed = process_row(DatasetKind.ITEMS, items_row(item_number="9901"), None)

    assert processed.reasons == ()
    assert processed.values is not None
