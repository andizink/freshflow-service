"""Ingest orchestration: parse, dedup, atomic load, and report (PLAN.md §3.1, §4.3, ADR-009).

Owns the transaction boundary: a dataset's rows are replaced atomically
(ADR-009), so a failed or partial ingest never leaves a dataset half
updated.
"""

from typing import IO

from sqlalchemy.orm import Session

from app.common.enums import DatasetKind
from app.schemas.ingest import IngestReport


def ingest_dataset(session: Session, dataset: DatasetKind, file: IO[bytes]) -> IngestReport:
    """Ingest ``file`` as ``dataset``, replacing the dataset atomically.

    Pipeline: stream rows via :func:`app.ingest.parser.read_rows` -> apply
    :func:`app.ingest.rules.process_row` (N1-N6, Q1/Q2/Q3/Q5) -> deduplicate
    on :func:`app.ingest.rules.key_for` (N7 exact duplicates silently
    dropped and counted; Q4 conflicting duplicates quarantined, first
    occurrence still loaded) -> within one transaction, delete the
    dataset's existing rows and bulk-insert the accepted rows -> persist an
    :class:`~app.models.ingest_job.IngestJob` with the resulting
    :class:`~app.schemas.ingest.IngestReport` and any
    :class:`~app.models.quarantine_row.QuarantineRow` rows -> return the
    report.

    Ingesting the ``items`` dataset loads the first-class catalog; ingesting
    any per-store dataset (``inventory``, ``orderable-items``,
    ``order-recommendations``) checks each row's ``item_number`` against the
    catalog currently persisted in ``session`` (Q2). Ingesting a per-store
    dataset before ``items`` is allowed (PLAN.md §3.1) — the report will
    simply reflect an empty or partial catalog via ``unknown_item``
    quarantine counts and a warning recommending items-first order.

    Args:
        session: The active database session; the caller controls its
            lifecycle (see :func:`app.db.get_session`).
        dataset: Which dataset ``file`` represents.
        file: The uploaded CSV, as a binary file-like object.

    Returns:
        The :class:`~app.schemas.ingest.IngestReport` summarizing the run.

    Raises:
        app.ingest.parser.HeaderError: If the CSV header does not match the
            expected columns for ``dataset``.
    """
    raise NotImplementedError
