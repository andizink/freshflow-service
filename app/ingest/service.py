"""Ingest orchestration: parse, dedup, atomic load, and report (PLAN.md §3.1, §4.3, ADR-009).

Owns the transaction boundary: a dataset's rows are replaced atomically
(ADR-009), so a failed or partial ingest never leaves a dataset half
updated.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import IO

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.common.enums import DatasetKind, ReasonCode
from app.db import Base
from app.ingest import rules
from app.ingest.parser import read_rows
from app.models.ingest_job import IngestJob
from app.models.inventory import InventoryRecord
from app.models.item import Item
from app.models.order_recommendation import OrderRecommendation
from app.models.orderable_item import OrderableItem
from app.models.quarantine_row import QuarantineRow
from app.schemas.ingest import IngestReport, QuarantinePage, QuarantineRowOut

logger = logging.getLogger(__name__)

#: ORM model owning each dataset's table, used for the replace-per-dataset
#: delete + bulk-insert step (PLAN.md §4.1, ADR-009).
_MODEL_BY_DATASET: dict[DatasetKind, type[Base]] = {
    DatasetKind.ITEMS: Item,
    DatasetKind.INVENTORY: InventoryRecord,
    DatasetKind.ORDERABLE_ITEMS: OrderableItem,
    DatasetKind.ORDER_RECOMMENDATIONS: OrderRecommendation,
}

#: Warning key emitted by :func:`app.ingest.rules.process_row` for
#: fractional inventory quantities (N6); gets its own summarized warning
#: line rather than the generic fallback format.
_FRACTIONAL_QUANTITY_WARNING_KEY = "fractional_quantity"


class IngestNotFoundError(LookupError):
    """Raised when a query targets an unknown ``ingest_id``.

    Deliberately not registered as a global FastAPI exception handler:
    ``app/ingest/router.py`` catches it directly and returns a 404
    ``ProblemDetail`` response, keeping the ingest package's error
    handling local to the ingest package. Centralizing it in ``main.py``
    would work too; local handling was kept to avoid a circular import
    between ``main`` and this router.

    Attributes:
        ingest_id: The ingest run identifier that was not found.
    """

    def __init__(self, ingest_id: str) -> None:
        """Initialize the error with the unknown ingest run identifier.

        Args:
            ingest_id: The ingest run identifier that was not found.
        """
        self.ingest_id = ingest_id
        super().__init__(f"Unknown ingest_id: {ingest_id!r}")


def _merge_counts(total: dict[str, int], delta: dict[str, int]) -> None:
    """Accumulate ``delta`` counts into ``total`` in place.

    Args:
        total: The running totals dict, mutated in place.
        delta: Counts to add, keyed the same way as ``total``.
    """
    for key, value in delta.items():
        total[key] = total.get(key, 0) + value


def _merge_reason_counts(total: dict[str, int], reasons: list[ReasonCode]) -> None:
    """Increment ``total`` by one for each reason code in ``reasons``.

    A single quarantined row may carry more than one reason (e.g. both
    ``negative_quantity`` and ``unknown_item``); each reason is counted
    independently in ``quarantine_summary``, while the row itself is
    counted once in ``quarantined_rows``.

    Args:
        total: The running reason-count totals dict, mutated in place.
        reasons: The reason codes carried by one quarantined row.
    """
    for reason in reasons:
        total[reason.value] = total.get(reason.value, 0) + 1


def _load_known_items(session: Session, dataset: DatasetKind) -> frozenset[int] | None:
    """Build the known-item-numbers set used for the Q2 unknown-item check.

    Args:
        session: The active database session.
        dataset: The dataset currently being ingested.

    Returns:
        ``None`` when ``dataset`` is :attr:`DatasetKind.ITEMS` (the catalog
        check does not apply to the catalog itself); otherwise a
        (possibly empty) frozenset of the ``item_number`` values currently
        persisted in the ``items`` table.
    """
    if dataset is DatasetKind.ITEMS:
        return None
    item_numbers = session.execute(select(Item.item_number)).scalars().all()
    return frozenset(item_numbers)


def _build_warnings(
    known_items: frozenset[int] | None,
    quarantine_summary: dict[str, int],
    row_warnings: dict[str, int],
) -> list[str]:
    """Build the human-readable ``warnings`` list for an ingest report.

    Args:
        known_items: The catalog snapshot used for this ingest's Q2 check
            (``None`` for the ``items`` dataset itself).
        quarantine_summary: Per-reason-code quarantine counts for this run.
        row_warnings: Aggregated non-rejecting per-row warning counts (e.g.
            ``fractional_quantity``) returned by
            :func:`app.ingest.rules.process_row`.

    Returns:
        Ordered, human-readable warning strings.
    """
    warnings: list[str] = []

    unknown_item_count = quarantine_summary.get(ReasonCode.UNKNOWN_ITEM.value, 0)
    if known_items is not None and len(known_items) == 0 and unknown_item_count > 0:
        warnings.append(
            "item catalog is empty — rows referencing items were quarantined as "
            "unknown_item; ingest items.csv first"
        )

    conflicting = quarantine_summary.get(ReasonCode.CONFLICTING_DUPLICATE.value, 0)
    if conflicting:
        warnings.append(
            f"{conflicting} rows quarantined as conflicting_duplicate "
            "(same key, differing values); first occurrence loaded"
        )

    fractional = row_warnings.get(_FRACTIONAL_QUANTITY_WARNING_KEY, 0)
    if fractional:
        warnings.append(
            f"{fractional} rows have a fractional quantity (stored exactly, rounded for display)"
        )

    for key, count in row_warnings.items():
        if key == _FRACTIONAL_QUANTITY_WARNING_KEY:
            continue
        warnings.append(f"{count} rows flagged: {key}")

    return warnings


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

    All rows are read and classified entirely in memory *before* any
    database mutation happens, so a header/parse failure
    (:class:`~app.ingest.parser.HeaderError`, raised while streaming) never
    touches the previously-loaded data for this dataset — atomicity is
    achieved by construction, not just by the wrapping transaction.

    Dedup/quarantine semantics (N7/Q4), precisely:

    * Every received row lands in exactly one of three buckets: **loaded**
      (the first row seen for its :func:`~app.ingest.rules.key_for` key,
      among rows that passed N1-N6/Q1/Q2/Q3/Q5), **deduplicated** (N7: a
      later row with the *same* key and an identical normalized payload as
      the row already loaded for that key - silently dropped, counted),
      or **rejected** (either failed Q1/Q2/Q3/Q5 outright, or is a later
      row with the same key as an already-loaded row but a *different*
      payload - Q4 conflicting duplicate, not loaded).
    * This gives the exact invariant ``received_rows == loaded_rows +
      deduplicated_rows + rows_rejected``, where ``rows_rejected`` is the
      count of rows in the "rejected" bucket above.
    * ``quarantined_rows`` (and the number of persisted
      :class:`~app.models.quarantine_row.QuarantineRow` records) is
      **not** ``rows_rejected`` when Q4 occurs: for every key with at
      least one conflicting duplicate, the *already-loaded* first
      occurrence's raw row is *also* copied into quarantine (so both the
      accepted and the conflicting version are auditable), per PLAN.md
      §4.3 Q4. So ``quarantined_rows == rows_rejected + bonus_count``,
      where ``bonus_count`` is the number of distinct keys that had at
      least one conflicting duplicate. Every row in that bonus set is
      simultaneously reflected in ``loaded_rows`` (it was, and remains,
      loaded) and in ``quarantined_rows`` (its raw copy is archived) -
      this is intentional double bookkeeping, not a bug, and is exercised
      directly by the ``conflicting_duplicate`` integration test.
    * ``quarantine_summary`` counts occurrences of each reason code across
      *all* persisted quarantine rows (a row with multiple simultaneous Q1
      -Q5 reasons is counted once per reason there, but once in
      ``quarantined_rows``).

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
    model = _MODEL_BY_DATASET[dataset]
    known_items = _load_known_items(session, dataset)

    received_rows = 0
    # Zero-filled from the fixed key vocabulary (PLAN.md §3.1 report example)
    # so consumers never need to distinguish an absent key from a zero count.
    normalizations: dict[str, int] = dict.fromkeys(rules.NORMALIZATION_KEYS, 0)
    row_warnings: dict[str, int] = {}
    quarantine_summary: dict[str, int] = {}
    quarantine_entries: list[tuple[int, dict[str, str], list[ReasonCode]]] = []

    seen: dict[tuple[object, ...], tuple[int, dict[str, str], dict[str, object]]] = {}
    loaded_order: list[tuple[object, ...]] = []
    conflict_flagged: set[tuple[object, ...]] = set()
    deduplicated_rows = 0

    for row_number, raw_row in read_rows(file, dataset):
        received_rows += 1
        processed = rules.process_row(dataset, raw_row, known_items)
        _merge_counts(normalizations, processed.normalizations)
        _merge_counts(row_warnings, processed.warnings)

        if processed.values is None:
            reasons = list(processed.reasons)
            quarantine_entries.append((row_number, raw_row, reasons))
            _merge_reason_counts(quarantine_summary, reasons)
            continue

        key = rules.key_for(dataset, processed.values)
        if key not in seen:
            seen[key] = (row_number, raw_row, processed.values)
            loaded_order.append(key)
            continue

        first_row_number, first_raw_row, first_values = seen[key]
        if processed.values == first_values:
            deduplicated_rows += 1
            continue

        # Q4: conflicting duplicate. First occurrence stays loaded; both
        # its raw row and this row's raw row are archived to quarantine.
        if key not in conflict_flagged:
            conflict_flagged.add(key)
            bonus_reasons = [ReasonCode.CONFLICTING_DUPLICATE]
            quarantine_entries.append((first_row_number, first_raw_row, bonus_reasons))
            _merge_reason_counts(quarantine_summary, bonus_reasons)
        current_reasons = [ReasonCode.CONFLICTING_DUPLICATE]
        quarantine_entries.append((row_number, raw_row, current_reasons))
        _merge_reason_counts(quarantine_summary, current_reasons)

    loaded_values = [seen[key][2] for key in loaded_order]
    loaded_rows = len(loaded_values)
    quarantined_rows = len(quarantine_entries)

    warnings = _build_warnings(known_items, quarantine_summary, row_warnings)

    if dataset is DatasetKind.ORDER_RECOMMENDATIONS and loaded_values:
        orderable_keys = set(
            session.execute(
                select(
                    OrderableItem.store_id,
                    OrderableItem.item_number,
                    OrderableItem.ordering_day,
                )
            ).all()
        )
        missing = sum(
            1
            for values in loaded_values
            if (values["store_id"], values["item_number"], values["ordering_day"])
            not in orderable_keys
        )
        if missing:
            warnings.append(
                f"{missing} recommendations reference no orderable window (loaded; flagged)"
            )

    ingest_id = uuid.uuid4().hex
    report = IngestReport(
        ingest_id=ingest_id,
        dataset=dataset,
        received_rows=received_rows,
        loaded_rows=loaded_rows,
        deduplicated_rows=deduplicated_rows,
        quarantined_rows=quarantined_rows,
        normalizations=normalizations,
        quarantine_summary=quarantine_summary,
        warnings=warnings,
    )

    try:
        session.execute(delete(model))
        if loaded_values:
            session.execute(insert(model), loaded_values)

        session.add(
            IngestJob(
                ingest_id=ingest_id,
                dataset=dataset.value,
                created_at=datetime.now(UTC),
                report=report.model_dump(mode="json"),
            )
        )
        for entry_row_number, entry_raw_row, entry_reasons in quarantine_entries:
            session.add(
                QuarantineRow(
                    ingest_id=ingest_id,
                    row_number=entry_row_number,
                    raw_row=entry_raw_row,
                    reasons=[reason.value for reason in entry_reasons],
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info(
        "ingest complete dataset=%s ingest_id=%s received=%d loaded=%d "
        "deduplicated=%d quarantined=%d warnings=%d",
        dataset.value,
        ingest_id,
        received_rows,
        loaded_rows,
        deduplicated_rows,
        quarantined_rows,
        len(warnings),
    )

    return report


def get_ingest_report(session: Session, ingest_id: str) -> IngestReport:
    """Re-fetch a past ingest run's report.

    Args:
        session: The active database session.
        ingest_id: The ingest run identifier.

    Returns:
        The stored :class:`~app.schemas.ingest.IngestReport`.

    Raises:
        IngestNotFoundError: If no ingest job exists for ``ingest_id``.
    """
    job = session.get(IngestJob, ingest_id)
    if job is None:
        raise IngestNotFoundError(ingest_id)
    return IngestReport.model_validate(job.report)


def get_quarantine_page(
    session: Session, ingest_id: str, limit: int, offset: int
) -> QuarantinePage:
    """Fetch one page of quarantined rows for a past ingest run.

    Args:
        session: The active database session.
        ingest_id: The ingest run identifier.
        limit: Maximum number of rows to return (caller is responsible for
            capping this, e.g. at 1000; see PLAN.md §3.3).
        offset: Number of rows to skip before collecting ``limit`` rows.

    Returns:
        A page of quarantined rows with their reasons.

    Raises:
        IngestNotFoundError: If no ingest job exists for ``ingest_id``.
    """
    job = session.get(IngestJob, ingest_id)
    if job is None:
        raise IngestNotFoundError(ingest_id)

    total = session.execute(
        select(func.count()).select_from(QuarantineRow).where(QuarantineRow.ingest_id == ingest_id)
    ).scalar_one()

    rows = (
        session.execute(
            select(QuarantineRow)
            .where(QuarantineRow.ingest_id == ingest_id)
            .order_by(QuarantineRow.row_number)
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )

    return QuarantinePage(
        ingest_id=ingest_id,
        total=total,
        limit=limit,
        offset=offset,
        rows=[
            QuarantineRowOut(
                row_number=row.row_number,
                raw_row=row.raw_row,
                reasons=[ReasonCode(reason) for reason in row.reasons],
            )
            for row in rows
        ],
    )
