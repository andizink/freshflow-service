"""Integration tests for the ingest API (PLAN.md §3.1, §3.3).

Exercises :func:`app.ingest.service.ingest_dataset` end to end through the
FastAPI ``TestClient`` against handcrafted fixture CSVs in
``tests/fixtures/``, one per defect class (PLAN.md §4.2/§4.3), plus the
report-retrieval, quarantine-audit, error, replace-idempotency, and
atomicity behaviors required by PLAN.md §3.1/§3.3.

Each fixture file isolates a single defect class so a failure points at
exactly one rule; the expected report numbers are asserted exactly, not
just "some rows were quarantined".
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.order_recommendation import OrderRecommendation

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


ZERO_NORMALIZATIONS: dict[str, int] = {
    "store_id_cleaned": 0,
    "item_number_float_coerced": 0,
    "date_format_converted": 0,
    "value_whitespace_stripped": 0,
    "casing_normalized": 0,
}


def expected_normalizations(**overrides: int) -> dict[str, int]:
    """Build a zero-filled normalizations dict with the given overrides."""
    return {**ZERO_NORMALIZATIONS, **overrides}


def _upload(client: TestClient, dataset: str, filename: str) -> Response:
    """POST a fixture CSV to the ingest endpoint for ``dataset``.

    Args:
        client: The test client.
        dataset: The ``DatasetKind`` path segment to ingest into.
        filename: The fixture file name under ``tests/fixtures/``.

    Returns:
        The raw ``httpx.Response``.
    """
    path = FIXTURES / filename
    with path.open("rb") as fh:
        return client.post(
            f"/api/v1/ingest/{dataset}",
            files={"file": (filename, fh, "text/csv")},
        )


def _ingest_catalog(client: TestClient) -> dict[str, object]:
    """Ingest the shared clean item catalog fixture.

    Args:
        client: The test client.

    Returns:
        The parsed JSON ingest report.
    """
    response = _upload(client, "items", "items_catalog.csv")
    assert response.status_code == 200
    return response.json()


# ---------------------------------------------------------------------------
# Clean file / catalog
# ---------------------------------------------------------------------------


def test_clean_items_catalog_loads_with_no_defects(client: TestClient) -> None:
    """A clean items file loads every row with zero normalizations/quarantine."""
    report = _ingest_catalog(client)

    assert report["dataset"] == "items"
    assert report["received_rows"] == 10
    assert report["loaded_rows"] == 10
    assert report["deduplicated_rows"] == 0
    assert report["quarantined_rows"] == 0
    assert report["normalizations"] == expected_normalizations()
    assert report["quarantine_summary"] == {}
    assert report["warnings"] == []
    assert isinstance(report["ingest_id"], str) and report["ingest_id"]


# ---------------------------------------------------------------------------
# N1: store_id normalization
# ---------------------------------------------------------------------------


def test_store_id_variants_are_normalized(client: TestClient) -> None:
    """N1: whitespace/casing store_id variants are cleaned and counted."""
    _ingest_catalog(client)
    response = _upload(client, "order-recommendations", "store_id_variants.csv")

    assert response.status_code == 200
    report = response.json()

    assert report["received_rows"] == 3
    assert report["loaded_rows"] == 3
    assert report["deduplicated_rows"] == 0
    assert report["quarantined_rows"] == 0
    assert report["quarantine_summary"] == {}
    assert report["normalizations"] == expected_normalizations(store_id_cleaned=2)
    assert report["warnings"] == [
        "3 recommendations reference no orderable window (loaded; flagged)"
    ]


# ---------------------------------------------------------------------------
# N2: item_number float coercion
# ---------------------------------------------------------------------------


def test_float_item_number_coerced_or_quarantined(client: TestClient) -> None:
    """N2: zero-fractional floats coerce; other fractions are quarantined."""
    _ingest_catalog(client)
    response = _upload(client, "order-recommendations", "float_item_number.csv")

    assert response.status_code == 200
    report = response.json()

    assert report["received_rows"] == 3
    assert report["loaded_rows"] == 2
    assert report["deduplicated_rows"] == 0
    assert report["quarantined_rows"] == 1
    assert report["quarantine_summary"] == {"invalid_value": 1}
    assert report["normalizations"] == expected_normalizations(item_number_float_coerced=1)
    assert report["warnings"] == [
        "2 recommendations reference no orderable window (loaded; flagged)"
    ]


# ---------------------------------------------------------------------------
# Q2: unknown item
# ---------------------------------------------------------------------------


def test_unknown_item_is_quarantined_against_loaded_catalog(client: TestClient) -> None:
    """Q2: an item_number missing from the loaded catalog is quarantined."""
    _ingest_catalog(client)
    response = _upload(client, "order-recommendations", "unknown_item.csv")

    assert response.status_code == 200
    report = response.json()

    assert report["received_rows"] == 2
    assert report["loaded_rows"] == 1
    assert report["quarantined_rows"] == 1
    assert report["quarantine_summary"] == {"unknown_item": 1}
    assert report["warnings"] == [
        "1 recommendations reference no orderable window (loaded; flagged)"
    ]


def test_unknown_item_warns_when_catalog_empty(client: TestClient) -> None:
    """Q2 + empty catalog: every referenced item is unknown, warning fires."""
    response = _upload(client, "order-recommendations", "unknown_item.csv")

    assert response.status_code == 200
    report = response.json()

    assert report["received_rows"] == 2
    assert report["loaded_rows"] == 0
    assert report["quarantined_rows"] == 2
    assert report["quarantine_summary"] == {"unknown_item": 2}
    assert report["warnings"] == [
        "item catalog is empty — rows referencing items were quarantined as "
        "unknown_item; ingest items.csv first"
    ]


# ---------------------------------------------------------------------------
# Q1: negative quantity
# ---------------------------------------------------------------------------


def test_negative_quantity_is_quarantined(client: TestClient) -> None:
    """Q1: recommended_quantity < 0 is quarantined."""
    _ingest_catalog(client)
    response = _upload(client, "order-recommendations", "negative_quantity.csv")

    assert response.status_code == 200
    report = response.json()

    assert report["received_rows"] == 2
    assert report["loaded_rows"] == 1
    assert report["quarantined_rows"] == 1
    assert report["quarantine_summary"] == {"negative_quantity": 1}


# ---------------------------------------------------------------------------
# Q5: delivery before ordering
# ---------------------------------------------------------------------------


def test_delivery_before_ordering_is_quarantined(client: TestClient) -> None:
    """Q5: delivery_day < ordering_day is quarantined."""
    _ingest_catalog(client)
    response = _upload(client, "order-recommendations", "delivery_before_ordering.csv")

    assert response.status_code == 200
    report = response.json()

    assert report["received_rows"] == 2
    assert report["loaded_rows"] == 1
    assert report["quarantined_rows"] == 1
    assert report["quarantine_summary"] == {"invalid_date_order": 1}


# ---------------------------------------------------------------------------
# N7 / Q4: dedup and conflicting duplicates
# ---------------------------------------------------------------------------


def test_exact_duplicates_are_deduplicated(client: TestClient) -> None:
    """N7: an identical-payload duplicate key row is silently dropped and counted."""
    _ingest_catalog(client)
    response = _upload(client, "order-recommendations", "exact_duplicates.csv")

    assert response.status_code == 200
    report = response.json()

    assert report["received_rows"] == 3
    assert report["loaded_rows"] == 2
    assert report["deduplicated_rows"] == 1
    assert report["quarantined_rows"] == 0
    assert report["quarantine_summary"] == {}


def test_conflicting_duplicates_keep_first_and_quarantine_both(client: TestClient) -> None:
    """Q4: a same-key, differing-payload row keeps the first load and quarantines both raw rows."""
    _ingest_catalog(client)
    response = _upload(client, "order-recommendations", "conflicting_duplicates.csv")

    assert response.status_code == 200
    report = response.json()

    assert report["received_rows"] == 3
    assert report["loaded_rows"] == 2
    assert report["deduplicated_rows"] == 0
    assert report["quarantined_rows"] == 2
    assert report["quarantine_summary"] == {"conflicting_duplicate": 2}
    assert report["warnings"] == [
        "2 rows quarantined as conflicting_duplicate "
        "(same key, differing values); first occurrence loaded",
        "2 recommendations reference no orderable window (loaded; flagged)",
    ]

    ingest_id = report["ingest_id"]
    quarantine = client.get(f"/api/v1/ingest/{ingest_id}/quarantine")
    assert quarantine.status_code == 200
    page = quarantine.json()
    assert page["total"] == 2
    reasons = {tuple(row["reasons"]) for row in page["rows"]}
    assert reasons == {("conflicting_duplicate",)}
    quantities = sorted(int(row["raw_row"]["recommended_quantity"]) for row in page["rows"])
    assert quantities == [5, 9]


# ---------------------------------------------------------------------------
# N3: DD/MM/YYYY dates ; N6: fractional quantities
# ---------------------------------------------------------------------------


def test_dd_mm_yyyy_dates_are_normalized_and_bad_dates_quarantined(client: TestClient) -> None:
    """N3: day-first slash dates convert; a date fitting neither format is quarantined."""
    _ingest_catalog(client)
    response = _upload(client, "inventory", "dd_mm_yyyy_dates.csv")

    assert response.status_code == 200
    report = response.json()

    assert report["received_rows"] == 3
    assert report["loaded_rows"] == 2
    assert report["deduplicated_rows"] == 0
    assert report["quarantined_rows"] == 1
    assert report["quarantine_summary"] == {"invalid_value": 1}
    assert report["normalizations"] == expected_normalizations(date_format_converted=1)
    assert report["warnings"] == []


def test_fractional_quantity_is_loaded_with_warning(client: TestClient) -> None:
    """N6: fractional inventory quantities load exactly and produce one warning line."""
    _ingest_catalog(client)
    response = _upload(client, "inventory", "fractional_quantities.csv")

    assert response.status_code == 200
    report = response.json()

    assert report["received_rows"] == 2
    assert report["loaded_rows"] == 2
    assert report["quarantined_rows"] == 0
    assert report["warnings"] == [
        "1 rows have a fractional quantity (stored exactly, rounded for display)"
    ]


# ---------------------------------------------------------------------------
# Cross-file warning absence when an orderable window matches
# ---------------------------------------------------------------------------


def test_recommendations_with_matching_orderable_window_have_no_gap_warning(
    client: TestClient,
) -> None:
    """No cross-file warning is raised when every loaded recommendation has a window."""
    _ingest_catalog(client)
    orderable_response = _upload(client, "orderable-items", "orderable_items_clean.csv")
    assert orderable_response.status_code == 200

    response = _upload(client, "order-recommendations", "order_recommendations_matching.csv")
    assert response.status_code == 200
    report = response.json()

    assert report["received_rows"] == 2
    assert report["loaded_rows"] == 2
    assert report["quarantined_rows"] == 0
    assert report["warnings"] == []


# ---------------------------------------------------------------------------
# Report retrieval
# ---------------------------------------------------------------------------


def test_get_ingest_report_returns_stored_report(client: TestClient) -> None:
    """GET /ingest/{ingest_id} re-fetches the exact report from the ingest."""
    report = _ingest_catalog(client)
    ingest_id = report["ingest_id"]

    response = client.get(f"/api/v1/ingest/{ingest_id}")

    assert response.status_code == 200
    assert response.json() == report


def test_get_ingest_report_404_for_unknown_id(client: TestClient) -> None:
    """GET /ingest/{ingest_id} 404s with a problem+json body for an unknown id."""
    response = client.get("/api/v1/ingest/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert "does-not-exist" in body["detail"]


def test_get_ingest_quarantine_404_for_unknown_id(client: TestClient) -> None:
    """GET /ingest/{ingest_id}/quarantine 404s with a problem+json body for an unknown id."""
    response = client.get("/api/v1/ingest/does-not-exist/quarantine")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_quarantine_endpoint_preserves_raw_rows_and_reasons(client: TestClient) -> None:
    """The quarantine audit endpoint returns exact raw rows and reason codes."""
    _ingest_catalog(client)
    response = _upload(client, "order-recommendations", "negative_quantity.csv")
    ingest_id = response.json()["ingest_id"]

    page = client.get(f"/api/v1/ingest/{ingest_id}/quarantine").json()

    assert page["ingest_id"] == ingest_id
    assert page["total"] == 1
    assert page["limit"] == 100
    assert page["offset"] == 0
    assert len(page["rows"]) == 1
    row = page["rows"][0]
    assert row["reasons"] == ["negative_quantity"]
    assert row["raw_row"] == {
        "store_id": "store_a",
        "item_number": "1001",
        "ordering_day": "2024-01-01",
        "delivery_day": "2024-01-02",
        "recommended_quantity": "-5",
    }


def test_quarantine_endpoint_pagination(client: TestClient) -> None:
    """limit/offset paginate the quarantine rows and total reflects the full count."""
    _ingest_catalog(client)
    response = _upload(client, "order-recommendations", "conflicting_duplicates.csv")
    ingest_id = response.json()["ingest_id"]

    first_page = client.get(f"/api/v1/ingest/{ingest_id}/quarantine?limit=1&offset=0").json()
    second_page = client.get(f"/api/v1/ingest/{ingest_id}/quarantine?limit=1&offset=1").json()

    assert first_page["total"] == 2
    assert len(first_page["rows"]) == 1
    assert second_page["total"] == 2
    assert len(second_page["rows"]) == 1
    assert first_page["rows"][0]["row_number"] != second_page["rows"][0]["row_number"]


def test_quarantine_limit_capped_at_1000(client: TestClient) -> None:
    """A requested limit above 1000 is silently capped at 1000."""
    _ingest_catalog(client)
    response = _upload(client, "order-recommendations", "negative_quantity.csv")
    ingest_id = response.json()["ingest_id"]

    page = client.get(f"/api/v1/ingest/{ingest_id}/quarantine?limit=5000").json()

    assert page["limit"] == 1000


# ---------------------------------------------------------------------------
# Header / empty file errors
# ---------------------------------------------------------------------------


def test_bad_header_returns_400_with_expected_and_found(client: TestClient) -> None:
    """A CSV with the wrong header columns 400s, listing expected vs found."""
    response = _upload(client, "order-recommendations", "bad_header_recommendations.csv")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 400
    detail = body["detail"]
    assert "expected" in detail.lower()
    assert "found" in detail.lower()
    assert "recommended_quantity" in detail
    assert "qty" in detail


def test_empty_file_returns_400(client: TestClient) -> None:
    """A zero-byte upload fails header validation and 400s."""
    response = _upload(client, "order-recommendations", "empty.csv")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")


def test_invalid_dataset_path_segment_returns_422(client: TestClient) -> None:
    """An unrecognized dataset path segment 422s via FastAPI enum validation."""
    path = FIXTURES / "items_catalog.csv"
    with path.open("rb") as fh:
        response = client.post(
            "/api/v1/ingest/not-a-real-dataset",
            files={"file": ("items_catalog.csv", fh, "text/csv")},
        )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Oversized upload (413)
# ---------------------------------------------------------------------------


def test_oversized_upload_returns_413(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """An upload larger than settings.max_upload_bytes 413s without loading."""
    import app.config as config_module

    monkeypatch.setenv("FRESHFLOW_MAX_UPLOAD_BYTES", "10")
    config_module.get_settings.cache_clear()
    try:
        response = _upload(client, "items", "items_catalog.csv")

        assert response.status_code == 413
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["status"] == 413
    finally:
        config_module.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Replace idempotency and atomicity
# ---------------------------------------------------------------------------


def test_reingest_same_file_is_idempotent(client: TestClient, session: Session) -> None:
    """Re-ingesting the same clean file twice yields identical loaded counts and row count."""
    _ingest_catalog(client)
    _upload(client, "orderable-items", "orderable_items_clean.csv")

    first = _upload(client, "order-recommendations", "order_recommendations_matching.csv")
    second = _upload(client, "order-recommendations", "order_recommendations_matching.csv")

    assert first.status_code == 200
    assert second.status_code == 200
    first_report = first.json()
    second_report = second.json()

    assert first_report["loaded_rows"] == second_report["loaded_rows"] == 2
    assert first_report["ingest_id"] != second_report["ingest_id"]

    row_count = session.execute(select(func.count()).select_from(OrderRecommendation)).scalar_one()
    assert row_count == 2


def test_bad_ingest_after_good_ingest_leaves_previous_data_intact(
    client: TestClient, session: Session
) -> None:
    """A failed re-ingest (bad header) does not touch the previously loaded dataset."""
    _ingest_catalog(client)
    good = _upload(client, "order-recommendations", "order_recommendations_matching.csv")
    assert good.status_code == 200
    assert good.json()["loaded_rows"] == 2

    bad = _upload(client, "order-recommendations", "bad_header_recommendations.csv")
    assert bad.status_code == 400

    row_count = session.execute(select(func.count()).select_from(OrderRecommendation)).scalar_one()
    assert row_count == 2

    stored_ids = session.execute(select(OrderRecommendation.item_number)).scalars().all()
    assert sorted(stored_ids) == [1001, 1002]


def test_replace_load_removes_rows_not_in_new_file(client: TestClient, session: Session) -> None:
    """Re-ingesting a dataset with fewer rows replaces (not merges) the table."""
    _ingest_catalog(client)
    _upload(client, "order-recommendations", "order_recommendations_matching.csv")
    row_count_before = session.execute(
        select(func.count()).select_from(OrderRecommendation)
    ).scalar_one()
    assert row_count_before == 2

    smaller = _upload(client, "order-recommendations", "negative_quantity.csv")
    assert smaller.status_code == 200
    assert smaller.json()["loaded_rows"] == 1

    row_count_after = session.execute(
        select(func.count()).select_from(OrderRecommendation)
    ).scalar_one()
    assert row_count_after == 1
    stored_ids = session.execute(select(OrderRecommendation.item_number)).scalars().all()
    assert stored_ids == [1002]


def test_non_utf8_upload_returns_400_and_leaves_data_intact(
    client: TestClient, session: Session
) -> None:
    """A non-UTF-8 file is rejected with 400 problem+json, atomically.

    The valid header is followed by bytes that cannot decode as UTF-8; the
    response must be a 400 ``Invalid CSV encoding`` problem detail, and data
    loaded by a previous good ingest must be untouched.
    """
    _ingest_catalog(client)
    good = _upload(client, "order-recommendations", "order_recommendations_matching.csv")
    assert good.status_code == 200
    before = session.scalar(select(func.count()).select_from(OrderRecommendation))

    payload = (
        b"store_id,item_number,ordering_day,delivery_day,recommended_quantity\n"
        b"\xff\xfe\x00bad,1,2024-01-01,2024-01-02,5\n"
    )
    response = client.post(
        "/api/v1/ingest/order-recommendations",
        files={"file": ("bad.csv", payload, "text/csv")},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["title"] == "Invalid CSV encoding"
    assert body["status"] == 400
    assert "UTF-8" in body["detail"]
    after = session.scalar(select(func.count()).select_from(OrderRecommendation))
    assert after == before


@pytest.mark.parametrize(
    ("query", "field"),
    [("limit=-5", "limit"), ("limit=0", "limit"), ("offset=-3", "offset")],
)
def test_quarantine_pagination_rejects_non_positive_bounds(
    client: TestClient, query: str, field: str
) -> None:
    """Negative/zero limit and negative offset are rejected with 422.

    A negative ``LIMIT`` would disable SQLite's row cap entirely, silently
    bypassing the 1000-row page ceiling.
    """
    _ingest_catalog(client)
    report = _upload(client, "order-recommendations", "negative_quantity.csv").json()

    response = client.get(f"/api/v1/ingest/{report['ingest_id']}/quarantine?{query}")

    assert response.status_code == 422
    assert any(field in str(err.get("loc", [])) for err in response.json()["detail"])
