"""Stores API routes (PLAN.md §3.3)."""

from fastapi import APIRouter

from app.db import SessionDep
from app.schemas.stores import StoresResponse

router = APIRouter(tags=["stores"])


@router.get("/stores", response_model=StoresResponse)
async def list_stores(session: SessionDep) -> StoresResponse:
    """List all known stores with their per-dataset row counts.

    Args:
        session: Injected database session.

    Returns:
        The known stores and their row counts.

    Raises:
        NotImplementedError: Always; this is a frozen contract stub.
    """
    raise NotImplementedError
