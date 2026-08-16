"""ORM model for ingest job records (PLAN.md §4.1)."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IngestJob(Base):
    """A record of one ingest run, including its machine-readable report.

    Attributes:
        ingest_id: Primary key, a uuid4 hex string identifying the run.
        dataset: The dataset kind that was ingested (see
            :class:`app.common.enums.DatasetKind`).
        created_at: Timezone-aware timestamp of when the ingest completed.
        report: The full ingest report, JSON-serialized
            (see :class:`app.schemas.ingest.IngestReport`).
    """

    __tablename__ = "ingest_jobs"

    ingest_id: Mapped[str] = mapped_column(primary_key=True)
    dataset: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    report: Mapped[dict[str, Any]] = mapped_column(JSON)
