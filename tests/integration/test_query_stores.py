"""Integration tests for ``GET /api/v1/stores``.

Seeds the isolated test database directly through the ORM models — going
through the ingest pipeline here would couple these tests to ingest
behavior, which has its own suite — and exercises the endpoint through
the FastAPI ``TestClient``.
"""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.inventory import InventoryRecord
from app.models.order_recommendation import OrderRecommendation
from app.models.orderable_item import OrderableItem

STORES_PATH = "/api/v1/stores"


def test_stores_counts_and_sorting(client: TestClient, session: Session) -> None:
    """Row counts per table are aggregated per store and results are sorted."""
    day = date(2024, 1, 1)

    # store_b: two inventory rows, one recommendation row, no orderable window.
    session.add_all(
        [
            InventoryRecord(store_id="store_b", item_number=1001, day=day, quantity=Decimal("1")),
            InventoryRecord(store_id="store_b", item_number=1002, day=day, quantity=Decimal("2")),
            OrderRecommendation(
                store_id="store_b",
                item_number=1001,
                ordering_day=day,
                delivery_day=date(2024, 1, 2),
                recommended_quantity=5,
            ),
        ]
    )
    # store_a: one inventory row, one orderable window, three recommendation rows.
    session.add_all(
        [
            InventoryRecord(store_id="store_a", item_number=1001, day=day, quantity=Decimal("3")),
            OrderableItem(
                store_id="store_a",
                item_number=1001,
                ordering_day=day,
                delivery_day=date(2024, 1, 2),
                purchase_price=Decimal("0.89"),
                suggested_retail_price=Decimal("1.49"),
                profit_margin=None,
                tags=[],
                category="Fruits",
            ),
            OrderRecommendation(
                store_id="store_a",
                item_number=1001,
                ordering_day=day,
                delivery_day=date(2024, 1, 2),
                recommended_quantity=5,
            ),
            OrderRecommendation(
                store_id="store_a",
                item_number=1002,
                ordering_day=day,
                delivery_day=date(2024, 1, 2),
                recommended_quantity=6,
            ),
            OrderRecommendation(
                store_id="store_a",
                item_number=1003,
                ordering_day=day,
                delivery_day=date(2024, 1, 2),
                recommended_quantity=7,
            ),
        ]
    )
    session.commit()

    response = client.get(STORES_PATH)

    assert response.status_code == 200
    stores = response.json()["stores"]
    assert [s["store_id"] for s in stores] == ["store_a", "store_b"]

    store_a, store_b = stores
    assert store_a == {
        "store_id": "store_a",
        "inventory_rows": 1,
        "recommendation_rows": 3,
        "orderable_rows": 1,
    }
    assert store_b == {
        "store_id": "store_b",
        "inventory_rows": 2,
        "recommendation_rows": 1,
        "orderable_rows": 0,
    }


def test_stores_empty_when_no_data(client: TestClient, session: Session) -> None:
    """No seeded data yields an empty stores list."""
    response = client.get(STORES_PATH)

    assert response.status_code == 200
    assert response.json() == {"stores": []}
