"""Pydantic request/response models — the API contract (PLAN.md §3)."""

from app.schemas.errors import ProblemDetail
from app.schemas.ingest import IngestReport, QuarantinePage, QuarantineRowOut
from app.schemas.recommendations import RecommendationItem, RecommendationsResponse
from app.schemas.stores import StoreInfo, StoresResponse

__all__ = [
    "IngestReport",
    "ProblemDetail",
    "QuarantinePage",
    "QuarantineRowOut",
    "RecommendationItem",
    "RecommendationsResponse",
    "StoreInfo",
    "StoresResponse",
]
