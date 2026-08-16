"""Ingest API routes: upload, report re-fetch, quarantine audit (PLAN.md §3.1, §3.3).

Routers stay thin — all business logic lives in
:func:`app.ingest.service.ingest_dataset` and its companions; these
handlers only wire HTTP concerns (path/query params, upload-size
enforcement, the DB session dependency, and translating domain exceptions
into RFC 9457 ``application/problem+json`` responses) to the service layer.

Two error paths are handled directly here rather than via a global
``app.main`` exception handler, since this lane does not own ``main.py``:

* Oversized uploads (413) are detected while streaming the multipart body,
  before the service layer ever sees the file.
* Unknown ``ingest_id`` lookups (404,
  :class:`app.ingest.service.IngestNotFoundError`) are caught locally.

The 400 "bad CSV header" path (:class:`app.ingest.parser.HeaderError`) is
*not* handled here: it is already mapped to a 400 problem response by a
handler registered in ``app.main.create_app`` (see that module), so it is
left to propagate.
"""

import io
import logging
from typing import Annotated

from fastapi import APIRouter, Query, UploadFile
from fastapi.responses import JSONResponse

from app.common.enums import DatasetKind
from app.config import get_settings
from app.db import SessionDep
from app.ingest import service
from app.schemas.errors import ProblemDetail
from app.schemas.ingest import IngestReport, QuarantinePage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingest"])

#: Chunk size used while streaming the upload body to enforce
#: ``settings.max_upload_bytes`` without buffering more than one chunk's
#: worth of over-limit data at a time.
_UPLOAD_READ_CHUNK_BYTES = 1_000_000

#: Quarantine page size hard cap (PLAN.md §3.3), independent of whatever
#: ``limit`` the caller requests.
_QUARANTINE_LIMIT_CAP = 1000


def _problem_response(status: int, title: str, detail: str | None = None) -> JSONResponse:
    """Build an RFC 9457 ``application/problem+json`` response.

    Mirrors the private helper of the same name in ``app.main`` (ADR-011);
    duplicated here rather than imported to avoid a circular import, since
    ``app.main`` imports this module's ``router``.

    Args:
        status: The HTTP status code.
        title: A short, human-readable summary of the problem type.
        detail: A human-readable explanation specific to this occurrence.

    Returns:
        A :class:`~fastapi.responses.JSONResponse` with the problem+json
        content type and body.
    """
    problem = ProblemDetail(title=title, status=status, detail=detail)
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
    )


@router.post("/ingest/{dataset}", response_model=IngestReport)
async def ingest_dataset_endpoint(
    dataset: DatasetKind,
    file: UploadFile,
    session: SessionDep,
) -> IngestReport | JSONResponse:
    """Upload and atomically replace one dataset.

    Args:
        dataset: Which dataset ``file`` represents.
        file: The uploaded CSV, as multipart form field ``file``.
        session: Injected database session.

    Returns:
        The ingest report for this run (200), or a 413
        ``application/problem+json`` response if the upload exceeds
        ``settings.max_upload_bytes``.

    Raises:
        app.ingest.parser.HeaderError: If the CSV header does not match the
            expected columns for ``dataset``; mapped to 400 by the handler
            registered in ``app.main``.
    """
    max_bytes = get_settings().max_upload_bytes
    buffer = io.BytesIO()
    total_bytes = 0
    while True:
        chunk = await file.read(_UPLOAD_READ_CHUNK_BYTES)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            await file.close()
            logger.info("rejected oversized upload dataset=%s bytes>%d", dataset.value, max_bytes)
            return _problem_response(
                413,
                "Upload too large",
                f"upload exceeds the {max_bytes}-byte limit (settings.max_upload_bytes)",
            )
        buffer.write(chunk)
    buffer.seek(0)

    report = service.ingest_dataset(session, dataset, buffer)
    logger.info("ingest request completed dataset=%s ingest_id=%s", dataset.value, report.ingest_id)
    return report


@router.get("/ingest/{ingest_id}", response_model=IngestReport)
async def get_ingest_report(
    ingest_id: str,
    session: SessionDep,
) -> IngestReport | JSONResponse:
    """Re-fetch a past ingest run's report.

    Args:
        ingest_id: The ingest run identifier.
        session: Injected database session.

    Returns:
        The ingest report for the requested run (200), or a 404
        ``application/problem+json`` response if ``ingest_id`` is unknown.
    """
    try:
        return service.get_ingest_report(session, ingest_id)
    except service.IngestNotFoundError as exc:
        return _problem_response(404, "Ingest run not found", str(exc))


@router.get("/ingest/{ingest_id}/quarantine", response_model=QuarantinePage)
async def get_ingest_quarantine(
    ingest_id: str,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QuarantinePage | JSONResponse:
    """List quarantined rows for a past ingest run, paginated.

    Args:
        ingest_id: The ingest run identifier.
        limit: Maximum number of rows to return; must be positive and is
            capped at 1000 regardless of the requested value (a negative
            value would otherwise disable SQLite's ``LIMIT`` entirely,
            defeating the cap — rejected with 422).
        offset: Number of rows to skip before collecting ``limit`` rows;
            must be non-negative (422 otherwise).
        session: Injected database session.

    Returns:
        A page of quarantined rows with their reasons (200), or a 404
        ``application/problem+json`` response if ``ingest_id`` is unknown.
    """
    capped_limit = min(limit, _QUARANTINE_LIMIT_CAP)
    try:
        return service.get_quarantine_page(session, ingest_id, capped_limit, offset)
    except service.IngestNotFoundError as exc:
        return _problem_response(404, "Ingest run not found", str(exc))
