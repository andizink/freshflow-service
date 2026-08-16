"""Pydantic response models for the ingest API (PLAN.md §3.1)."""

from pydantic import BaseModel, ConfigDict

from app.common.enums import DatasetKind, ReasonCode


class IngestReport(BaseModel):
    """Machine-readable summary of one ingest run.

    Attributes:
        ingest_id: Unique identifier of this ingest run (uuid4 hex).
        dataset: The dataset kind that was ingested.
        received_rows: Total data rows read from the uploaded CSV.
        loaded_rows: Rows successfully normalized and persisted.
        deduplicated_rows: Rows dropped as exact-duplicate keys (N7/Q4).
        quarantined_rows: Rows rejected and persisted to quarantine (Q1-Q5).
        normalizations: Counts of applied normalizations, keyed by rule
            name (e.g. ``"store_id_cleaned"``, ``"item_number_float_coerced"``).
        quarantine_summary: Counts of quarantined rows, keyed by
            :class:`~app.common.enums.ReasonCode` value.
        warnings: Human-readable warnings that do not reject rows (e.g.
            cross-file referential gaps, fractional-quantity notes).
    """

    model_config = ConfigDict(frozen=True)

    ingest_id: str
    dataset: DatasetKind
    received_rows: int
    loaded_rows: int
    deduplicated_rows: int
    quarantined_rows: int
    normalizations: dict[str, int]
    quarantine_summary: dict[str, int]
    warnings: list[str]


class QuarantineRowOut(BaseModel):
    """One quarantined row, as returned by the audit endpoint.

    Attributes:
        row_number: 1-indexed source row number (header is row 1).
        raw_row: The original, unmodified row as a string-keyed dict.
        reasons: Reason codes explaining why the row was rejected.
    """

    model_config = ConfigDict(frozen=True)

    row_number: int
    raw_row: dict[str, str]
    reasons: list[ReasonCode]


class QuarantinePage(BaseModel):
    """A page of quarantined rows for one ingest run.

    Attributes:
        ingest_id: The ingest run these rows belong to.
        total: Total number of quarantined rows for the run (all pages).
        limit: The page size that was requested.
        offset: The offset that was requested.
        rows: The rows in this page.
    """

    model_config = ConfigDict(frozen=True)

    ingest_id: str
    total: int
    limit: int
    offset: int
    rows: list[QuarantineRowOut]
