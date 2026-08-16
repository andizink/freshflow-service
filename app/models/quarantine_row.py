"""ORM model for quarantined rows (PLAN.md §4.1, §4.3)."""

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class QuarantineRow(Base):
    """A single row rejected during ingest, kept for audit (Q1-Q5, ADR-010).

    Attributes:
        id: Surrogate primary key.
        ingest_id: Foreign key to the owning :class:`~app.models.ingest_job.IngestJob`.
        row_number: 1-indexed source row number (header is row 1, so data
            rows start at 2).
        raw_row: The original, unmodified row as a string-keyed dict.
        reasons: List of reason code strings
            (see :class:`app.common.enums.ReasonCode`) explaining rejection.
    """

    __tablename__ = "quarantine_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    ingest_id: Mapped[str] = mapped_column(ForeignKey("ingest_jobs.ingest_id"))
    row_number: Mapped[int] = mapped_column()
    raw_row: Mapped[dict[str, str]] = mapped_column(JSON)
    reasons: Mapped[list[str]] = mapped_column(JSON)
