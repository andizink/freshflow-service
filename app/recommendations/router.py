"""Recommendations API routes (PLAN.md §3.2)."""

from datetime import date

from fastapi import APIRouter

from app.db import SessionDep
from app.recommendations.service import get_recommendations
from app.schemas.recommendations import RecommendationsResponse

router = APIRouter(tags=["recommendations"])


@router.get("/stores/{store_id}/recommendations", response_model=RecommendationsResponse)
async def get_store_recommendations(
    store_id: str,
    day: date,
    session: SessionDep,
) -> RecommendationsResponse:
    """Fetch enriched order recommendations for a store and ordering day.

    Args:
        store_id: The store identifier, in any case/whitespace variant
            (normalized server-side).
        day: The ordering day, as an ISO ``YYYY-MM-DD`` query parameter.
        session: Injected database session.

    Returns:
        The enriched recommendations response.

    Raises:
        StoreNotFoundError: If ``store_id`` (after normalization) has no
            records in any dataset; mapped to a 404 problem response by
            the app-level exception handler in ``app.main``.
    """
    return get_recommendations(session, store_id, day)
