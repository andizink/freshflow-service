"""Ingest API routes: upload, report re-fetch, quarantine audit (PLAN.md §3.1, §3.3).

Routers stay thin — all business logic lives in
:func:`app.ingest.service.ingest_dataset` and its future companions; these
handlers only wire HTTP concerns (path/query params, the DB session
dependency) to the service layer.
"""

from fastapi import APIRouter, UploadFile

from app.common.enums import DatasetKind
from app.db import SessionDep
from app.schemas.ingest import IngestReport, QuarantinePage

router = APIRouter(tags=["ingest"])


@router.post("/ingest/{dataset}", response_model=IngestReport)
async def ingest_dataset_endpoint(
    dataset: DatasetKind,
    file: UploadFile,
    session: SessionDep,
) -> IngestReport:
    """Upload and atomically replace one dataset.

    Args:
        dataset: Which dataset ``file`` represents.
        file: The uploaded CSV, as multipart form field ``file``.
        session: Injected database session.

    Returns:
        The ingest report for this run.

    Raises:
        NotImplementedError: Always; this is a frozen contract stub.
    """
    raise NotImplementedError


@router.get("/ingest/{ingest_id}", response_model=IngestReport)
async def get_ingest_report(
    ingest_id: str,
    session: SessionDep,
) -> IngestReport:
    """Re-fetch a past ingest run's report.

    Args:
        ingest_id: The ingest run identifier.
        session: Injected database session.

    Returns:
        The ingest report for the requested run.

    Raises:
        NotImplementedError: Always; this is a frozen contract stub.
    """
    raise NotImplementedError


@router.get("/ingest/{ingest_id}/quarantine", response_model=QuarantinePage)
async def get_ingest_quarantine(
    ingest_id: str,
    session: SessionDep,
    limit: int = 100,
    offset: int = 0,
) -> QuarantinePage:
    """List quarantined rows for a past ingest run, paginated.

    Args:
        ingest_id: The ingest run identifier.
        limit: Maximum number of rows to return.
        offset: Number of rows to skip before collecting ``limit`` rows.
        session: Injected database session.

    Returns:
        A page of quarantined rows with their reasons.

    Raises:
        NotImplementedError: Always; this is a frozen contract stub.
    """
    raise NotImplementedError
