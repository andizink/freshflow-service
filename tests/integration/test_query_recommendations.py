"""Integration tests for ``GET /api/v1/stores/{store_id}/recommendations``.

Seeds the isolated test database directly through the ORM models — going
through the ingest pipeline here would couple these tests to ingest
behavior, which has its own suite — and exercises the endpoint through
the FastAPI ``TestClient``.
"""

from datetime import date
from decimal import Decimal
from urllib.parse import quote

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.inventory import InventoryRecord
from app.models.item import Item
from app.models.order_recommendation import OrderRecommendation
from app.models.orderable_item import OrderableItem

RECOMMENDATIONS_PATH = "/api/v1/stores/{store_id}/recommendations"


def _seed_item(
    session: Session,
    *,
    item_number: int,
    name: str = "Organic Bananas",
    category: str = "Fruits",
    is_bio: bool = False,
    purchase_price: str = "0.89",
    suggested_retail_price: str = "1.49",
) -> Item:
    """Insert and flush a catalog item row for a test."""
    item = Item(
        item_number=item_number,
        name=name,
        category=category,
        is_bio=is_bio,
        purchase_price=Decimal(purchase_price),
        suggested_retail_price=Decimal(suggested_retail_price),
    )
    session.add(item)
    session.commit()
    return item


def _seed_inventory(
    session: Session,
    *,
    store_id: str,
    item_number: int,
    day: date,
    quantity: str,
) -> InventoryRecord:
    """Insert and flush an inventory row for a test."""
    record = InventoryRecord(
        store_id=store_id, item_number=item_number, day=day, quantity=Decimal(quantity)
    )
    session.add(record)
    session.commit()
    return record


def _seed_window(
    session: Session,
    *,
    store_id: str,
    item_number: int,
    ordering_day: date,
    delivery_day: date,
    purchase_price: str = "0.99",
    suggested_retail_price: str = "1.59",
    tags: list[str] | None = None,
    category: str = "Fruits",
) -> OrderableItem:
    """Insert and flush an orderable-item window row for a test."""
    window = OrderableItem(
        store_id=store_id,
        item_number=item_number,
        ordering_day=ordering_day,
        delivery_day=delivery_day,
        purchase_price=Decimal(purchase_price),
        suggested_retail_price=Decimal(suggested_retail_price),
        profit_margin=None,
        tags=tags if tags is not None else [],
        category=category,
    )
    session.add(window)
    session.commit()
    return window


def _seed_recommendation(
    session: Session,
    *,
    store_id: str,
    item_number: int,
    ordering_day: date,
    delivery_day: date,
    recommended_quantity: int,
) -> OrderRecommendation:
    """Insert and flush an order-recommendation row for a test."""
    recommendation = OrderRecommendation(
        store_id=store_id,
        item_number=item_number,
        ordering_day=ordering_day,
        delivery_day=delivery_day,
        recommended_quantity=recommended_quantity,
    )
    session.add(recommendation)
    session.commit()
    return recommendation


def test_happy_path_full_enrichment(client: TestClient, session: Session) -> None:
    """A recommendation with catalog, inventory, and window data is fully enriched."""
    ordering_day = date(2024, 1, 1)
    delivery_day = date(2024, 1, 2)
    _seed_item(
        session,
        item_number=1001,
        name="Organic Bananas",
        category="Fruits",
        is_bio=False,
        purchase_price="0.89",
        suggested_retail_price="1.49",
    )
    _seed_inventory(
        session, store_id="store_a", item_number=1001, day=ordering_day, quantity="16.4"
    )
    _seed_window(
        session,
        store_id="store_a",
        item_number=1001,
        ordering_day=ordering_day,
        delivery_day=delivery_day,
        purchase_price="0.99",
        suggested_retail_price="1.59",
        tags=["new", "on_sale"],
        category="Fruits",
    )
    _seed_recommendation(
        session,
        store_id="store_a",
        item_number=1001,
        ordering_day=ordering_day,
        delivery_day=delivery_day,
        recommended_quantity=18,
    )

    response = client.get(
        RECOMMENDATIONS_PATH.format(store_id="store_a"), params={"day": "2024-01-01"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["store_id"] == "store_a"
    assert body["day"] == "2024-01-01"
    assert body["count"] == 1
    assert len(body["recommendations"]) == 1
    line = body["recommendations"][0]
    assert line == {
        "item_number": 1001,
        "item_name": "Organic Bananas",
        "category": "Fruits",
        "is_bio": False,
        "recommended_quantity": 18,
        "delivery_day": "2024-01-02",
        "current_inventory": 16,
        "purchase_price": 0.99,
        "suggested_retail_price": 1.59,
        "orderable": True,
        "tags": ["new", "on_sale"],
    }


def test_store_id_variant_input_resolves(client: TestClient, session: Session) -> None:
    """A whitespace/case store_id variant in the URL resolves to the normalized store."""
    ordering_day = date(2024, 1, 1)
    delivery_day = date(2024, 1, 2)
    _seed_recommendation(
        session,
        store_id="store_a",
        item_number=1001,
        ordering_day=ordering_day,
        delivery_day=delivery_day,
        recommended_quantity=5,
    )

    variant_store_id = quote(" STORE_A ")
    response = client.get(
        RECOMMENDATIONS_PATH.format(store_id=variant_store_id), params={"day": "2024-01-01"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["store_id"] == "store_a"
    assert body["count"] == 1


def test_unknown_store_returns_404_problem_detail(client: TestClient, session: Session) -> None:
    """An unrecognized store_id returns a 404 RFC 9457 problem response."""
    response = client.get(
        RECOMMENDATIONS_PATH.format(store_id="ghost_store"), params={"day": "2024-01-01"}
    )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert "title" in body
    assert body.get("detail")


def test_malformed_day_returns_422(client: TestClient, session: Session) -> None:
    """A day query parameter that isn't a valid date returns 422."""
    response = client.get(
        RECOMMENDATIONS_PATH.format(store_id="store_a"), params={"day": "not-a-date"}
    )

    assert response.status_code == 422


def test_missing_day_returns_422(client: TestClient, session: Session) -> None:
    """Omitting the required day query parameter returns 422."""
    response = client.get(RECOMMENDATIONS_PATH.format(store_id="store_a"))

    assert response.status_code == 422


def test_valid_store_day_without_recommendations_returns_empty_200(
    client: TestClient, session: Session
) -> None:
    """A known store with no recommendations on the given day returns 200, count 0."""
    _seed_recommendation(
        session,
        store_id="store_a",
        item_number=1001,
        ordering_day=date(2024, 1, 1),
        delivery_day=date(2024, 1, 2),
        recommended_quantity=5,
    )

    response = client.get(
        RECOMMENDATIONS_PATH.format(store_id="store_a"), params={"day": "2024-06-01"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["recommendations"] == []


def test_recommendation_without_orderable_window(client: TestClient, session: Session) -> None:
    """No orderable window: orderable is false, catalog prices are used, tags empty."""
    ordering_day = date(2024, 1, 1)
    delivery_day = date(2024, 1, 2)
    _seed_item(
        session,
        item_number=1002,
        name="Red Apples Gala",
        category="Fruits",
        is_bio=False,
        purchase_price="1.20",
        suggested_retail_price="1.99",
    )
    _seed_recommendation(
        session,
        store_id="store_a",
        item_number=1002,
        ordering_day=ordering_day,
        delivery_day=delivery_day,
        recommended_quantity=7,
    )

    response = client.get(
        RECOMMENDATIONS_PATH.format(store_id="store_a"), params={"day": "2024-01-01"}
    )

    assert response.status_code == 200
    line = response.json()["recommendations"][0]
    assert line["orderable"] is False
    assert line["tags"] == []
    assert line["purchase_price"] == 1.20
    assert line["suggested_retail_price"] == 1.99
    assert line["category"] == "Fruits"


def test_recommendation_without_inventory_row(client: TestClient, session: Session) -> None:
    """No same-day inventory row: current_inventory is None."""
    _seed_item(session, item_number=1003)
    _seed_recommendation(
        session,
        store_id="store_a",
        item_number=1003,
        ordering_day=date(2024, 1, 1),
        delivery_day=date(2024, 1, 2),
        recommended_quantity=3,
    )

    response = client.get(
        RECOMMENDATIONS_PATH.format(store_id="store_a"), params={"day": "2024-01-01"}
    )

    assert response.status_code == 200
    line = response.json()["recommendations"][0]
    assert line["current_inventory"] is None


def test_fractional_inventory_rounds_half_up(client: TestClient, session: Session) -> None:
    """Fractional inventory rounds half-up: 16.4 -> 16, 16.5 -> 17."""
    ordering_day = date(2024, 1, 1)
    delivery_day = date(2024, 1, 2)
    _seed_item(session, item_number=2001)
    _seed_item(session, item_number=2002)
    _seed_inventory(
        session, store_id="store_a", item_number=2001, day=ordering_day, quantity="16.4"
    )
    _seed_inventory(
        session, store_id="store_a", item_number=2002, day=ordering_day, quantity="16.5"
    )
    _seed_recommendation(
        session,
        store_id="store_a",
        item_number=2001,
        ordering_day=ordering_day,
        delivery_day=delivery_day,
        recommended_quantity=1,
    )
    _seed_recommendation(
        session,
        store_id="store_a",
        item_number=2002,
        ordering_day=ordering_day,
        delivery_day=delivery_day,
        recommended_quantity=1,
    )

    response = client.get(
        RECOMMENDATIONS_PATH.format(store_id="store_a"), params={"day": "2024-01-01"}
    )

    assert response.status_code == 200
    by_item = {line["item_number"]: line for line in response.json()["recommendations"]}
    assert by_item[2001]["current_inventory"] == 16
    assert by_item[2002]["current_inventory"] == 17


def test_recommendation_with_item_missing_from_catalog(
    client: TestClient, session: Session
) -> None:
    """An item absent from the catalog yields None item fields (deliberately unseeded)."""
    _seed_recommendation(
        session,
        store_id="store_a",
        item_number=9999,
        ordering_day=date(2024, 1, 1),
        delivery_day=date(2024, 1, 2),
        recommended_quantity=2,
    )

    response = client.get(
        RECOMMENDATIONS_PATH.format(store_id="store_a"), params={"day": "2024-01-01"}
    )

    assert response.status_code == 200
    line = response.json()["recommendations"][0]
    assert line["item_name"] is None
    assert line["category"] is None
    assert line["is_bio"] is None
    assert line["purchase_price"] is None
    assert line["suggested_retail_price"] is None
    assert line["orderable"] is False
    assert line["tags"] == []
