"""End-to-end tests against the four real challenge CSVs in ``data/``.

Ingests ``data/items.csv``, ``data/inventory.csv``,
``data/orderable_items.csv``, and ``data/order_recommendations.csv`` through
the real HTTP ingest endpoint (via the ``client`` fixture, an isolated
temp-file-backed SQLite database per PLAN.md §6.1) and asserts the resulting
reports match ``tests/e2e/expected_counts.json`` field by field. That file
is produced by ``scripts/generate_expected_counts.py``, an independently
written, standalone profiling script (PLAN.md §6.1/§9) - so the "expected"
numbers here are derived twice, by two different pieces of code, rather
than copied from the service under test.

Runs as one ordered scenario (single ``client`` fixture, sequential
ingests) rather than four independent tests, since the per-store datasets'
``unknown_item`` (Q2) counts and the recommendations/stores queries below
all depend on the catalog and per-store data already being loaded in a
specific order - matching ``scripts/load_all.sh`` and the real deployment
flow.
"""

import json
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from httpx import Response

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
EXPECTED_COUNTS_PATH = Path(__file__).resolve().parent / "expected_counts.json"

#: ``(dataset, source CSV filename)`` pairs, in the order they must be
#: ingested: ``items`` first, so the per-store files' Q2 unknown-item check
#: runs against a fully loaded catalog (PLAN.md §3.1).
DATASET_FILES: tuple[tuple[str, str], ...] = (
    ("items", "items.csv"),
    ("inventory", "inventory.csv"),
    ("orderable-items", "orderable_items.csv"),
    ("order-recommendations", "order_recommendations.csv"),
)

pytestmark = pytest.mark.e2e


def _load_expected_counts_raw() -> dict[str, dict[str, object]]:
    """Load the expected-counts fixture, stripping the ``_note`` metadata key.

    Returns:
        A mapping of dataset key to its expected ``IngestReport`` fields.
    """
    raw = json.loads(EXPECTED_COUNTS_PATH.read_text())
    return {key: value for key, value in raw.items() if key != "_note"}


def _upload(client: TestClient, dataset: str, filename: str) -> Response:
    """POST one real data CSV to the ingest endpoint for ``dataset``.

    Args:
        client: The test client.
        dataset: The ``DatasetKind`` path segment to ingest into.
        filename: The source file name under ``data/``.

    Returns:
        The raw ``httpx.Response``.
    """
    path = DATA_DIR / filename
    with path.open("rb") as fh:
        return client.post(
            f"/api/v1/ingest/{dataset}",
            files={"file": (filename, fh, "text/csv")},
        )


def _assert_report_matches_expected(report: dict[str, object], expected: dict[str, object]) -> None:
    """Assert every ``IngestReport`` field profiled by the expected-counts fixture matches.

    Args:
        report: The JSON ingest report returned by the API.
        expected: The corresponding expected-counts entry.
    """
    for field in (
        "received_rows",
        "loaded_rows",
        "deduplicated_rows",
        "quarantined_rows",
        "normalizations",
        "quarantine_summary",
    ):
        assert report[field] == expected[field], (
            f"{field}: got {report[field]!r}, expected {expected[field]!r}"
        )


@pytest.fixture(scope="module")
def expected_counts() -> dict[str, dict[str, object]]:
    """Provide the parsed ``expected_counts.json`` fixture, minus its ``_note``.

    Returns:
        A mapping of dataset key to its expected ``IngestReport`` fields.
    """
    return _load_expected_counts_raw()


def test_expected_counts_fixture_covers_all_four_datasets(
    expected_counts: dict[str, dict[str, object]],
) -> None:
    """The generated fixture has an entry for each of the four datasets."""
    assert set(expected_counts) == {
        "items",
        "inventory",
        "orderable-items",
        "order-recommendations",
    }


def test_ingest_all_four_real_files_matches_expected_counts(
    client: TestClient, expected_counts: dict[str, dict[str, object]]
) -> None:
    """Ingesting the four real CSVs produces reports matching the independent profile."""
    for dataset, filename in DATASET_FILES:
        response = _upload(client, dataset, filename)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["dataset"] == dataset
        _assert_report_matches_expected(report, expected_counts[dataset])


def test_recommendations_spot_check_store_a_item_1001(client: TestClient) -> None:
    """A known real row: store_a / item 1001 / 2024-01-01 matches the source data exactly.

    Cross-checked directly against the source CSVs:
      * ``order_recommendations.csv`` row 2: ``store_a,1001,2024-01-01,2024-01-02,18``.
      * ``inventory.csv`` row 2: ``store_a,1001,2024-01-01,16.4`` -> rounds
        half-up to ``16``.
      * ``orderable_items.csv`` row 19714: a window exists for this exact
        key (``store_a,1001,2024-01-01,2024-01-02,0.93,1.47,0.386,,Fruits``),
        so ``orderable`` is ``True`` and price/category come from the
        window, not the catalog.
      * ``items.csv`` row 2: item 1001 is "Organic Bananas".
    """
    for dataset, filename in DATASET_FILES:
        assert _upload(client, dataset, filename).status_code == 200

    response = client.get("/api/v1/stores/store_a/recommendations", params={"day": "2024-01-01"})
    assert response.status_code == 200
    body = response.json()
    assert body["store_id"] == "store_a"
    assert body["day"] == "2024-01-01"

    by_item = {item["item_number"]: item for item in body["recommendations"]}
    assert 1001 in by_item
    item = by_item[1001]

    assert item["item_name"] == "Organic Bananas"
    assert item["recommended_quantity"] == 18
    assert item["delivery_day"] == "2024-01-02"
    assert item["current_inventory"] == 16
    assert item["orderable"] is True
    assert item["category"] == "Fruits"
    assert item["is_bio"] is False
    assert item["purchase_price"] == pytest.approx(0.93)
    assert item["suggested_retail_price"] == pytest.approx(1.47)
    assert item["tags"] == []

    variant_store_id = quote(" STORE_A ")
    variant_response = client.get(
        f"/api/v1/stores/{variant_store_id}/recommendations", params={"day": "2024-01-01"}
    )
    assert variant_response.status_code == 200
    assert variant_response.json() == body


def test_stores_endpoint_lists_exactly_store_a_and_store_b(
    client: TestClient, expected_counts: dict[str, dict[str, object]]
) -> None:
    """``GET /stores`` lists exactly the two real stores, with plausible, exact counts."""
    for dataset, filename in DATASET_FILES:
        assert _upload(client, dataset, filename).status_code == 200

    response = client.get("/api/v1/stores")
    assert response.status_code == 200
    body = response.json()

    store_ids = [store["store_id"] for store in body["stores"]]
    assert store_ids == ["store_a", "store_b"]

    stores_by_id = {store["store_id"]: store for store in body["stores"]}
    for store in stores_by_id.values():
        assert store["inventory_rows"] > 0
        assert store["orderable_rows"] > 0
        assert store["recommendation_rows"] > 0

    # The real data has exactly two stores, so each dataset's per-store row
    # counts must sum exactly to that dataset's total loaded_rows - an
    # exact assertion derivable from expected_counts.json without needing a
    # third, per-store breakdown fixture.
    assert (
        sum(store["inventory_rows"] for store in body["stores"])
        == expected_counts["inventory"]["loaded_rows"]
    )
    assert (
        sum(store["orderable_rows"] for store in body["stores"])
        == expected_counts["orderable-items"]["loaded_rows"]
    )
    assert (
        sum(store["recommendation_rows"] for store in body["stores"])
        == expected_counts["order-recommendations"]["loaded_rows"]
    )


def test_quarantine_page_for_recommendations_includes_negative_quantity(
    client: TestClient,
) -> None:
    """The quarantine audit page for the recommendations ingest surfaces Q1 rows."""
    for dataset, filename in DATASET_FILES[:-1]:
        assert _upload(client, dataset, filename).status_code == 200

    response = _upload(client, "order-recommendations", "order_recommendations.csv")
    assert response.status_code == 200
    ingest_id = response.json()["ingest_id"]

    page = client.get(
        f"/api/v1/ingest/{ingest_id}/quarantine", params={"limit": 1000, "offset": 0}
    ).json()

    reasons_seen = {reason for row in page["rows"] for reason in row["reasons"]}
    assert "negative_quantity" in reasons_seen


def test_reingesting_order_recommendations_is_idempotent(
    client: TestClient, expected_counts: dict[str, dict[str, object]]
) -> None:
    """Re-ingesting the same real file twice yields byte-identical reports (minus ids)."""
    for dataset, filename in DATASET_FILES:
        assert _upload(client, dataset, filename).status_code == 200

    first = _upload(client, "order-recommendations", "order_recommendations.csv").json()
    second = _upload(client, "order-recommendations", "order_recommendations.csv").json()

    assert first["ingest_id"] != second["ingest_id"]
    for field in (
        "dataset",
        "received_rows",
        "loaded_rows",
        "deduplicated_rows",
        "quarantined_rows",
        "normalizations",
        "quarantine_summary",
        "warnings",
    ):
        assert first[field] == second[field]

    _assert_report_matches_expected(second, expected_counts["order-recommendations"])
