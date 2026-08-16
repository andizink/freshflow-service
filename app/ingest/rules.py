"""Row-level quarantine rules Q1-Q5 and the dedup key function (PLAN.md §4.3).

This module is the single source of truth for which rows get rejected and
why (ADR §4.3), referenced by both tests and ``docs/DATA_QUALITY.md``.
"""

from dataclasses import dataclass, field

from app.common.enums import DatasetKind, ReasonCode


@dataclass(frozen=True)
class ProcessedRow:
    """The outcome of running one raw CSV row through normalization + rules.

    Attributes:
        values: The normalized column values, keyed by field name, ready
            for ORM construction; ``None`` if the row was quarantined.
        reasons: Quarantine reason codes; empty if the row was accepted.
            Non-empty ``reasons`` implies ``values is None``.
        normalizations: Counts of normalizations applied while processing
            this row, keyed by normalization name (e.g.
            ``"store_id_cleaned"``). Accumulated by the caller into the
            ingest report's ``normalizations`` totals.
        warnings: Counts of non-rejecting warnings raised while processing
            this row, keyed by warning name (e.g. ``"fractional_quantity"``).
            Accumulated by the caller into the ingest report.
    """

    values: dict[str, object] | None
    reasons: tuple[ReasonCode, ...] = field(default_factory=tuple)
    normalizations: dict[str, int] = field(default_factory=dict)
    warnings: dict[str, int] = field(default_factory=dict)


def process_row(
    dataset: DatasetKind,
    raw: dict[str, str],
    known_items: frozenset[int] | None,
) -> ProcessedRow:
    """Normalize and validate one raw row for ``dataset``.

    Applies normalization rules N1-N6 (via :mod:`app.ingest.normalize`) and
    quarantine rules Q1, Q2, Q3, Q5 (Q4 - conflicting duplicates - is
    detected across rows by the caller using :func:`key_for`, not here).

    Args:
        dataset: Which dataset ``raw`` belongs to; determines which fields
            are expected and which rules apply.
        raw: The raw row as returned by :func:`app.ingest.parser.read_rows`.
        known_items: The set of known catalog item numbers, used for the
            Q2 unknown-item check on per-store datasets. ``None`` means the
            catalog check is skipped entirely — used when ingesting the
            ``items`` dataset itself, which defines the catalog.

    Returns:
        A :class:`ProcessedRow` describing either the normalized values
        (on success) or the quarantine reasons (on rejection).
    """
    raise NotImplementedError


def key_for(dataset: DatasetKind, values: dict[str, object]) -> tuple[object, ...]:
    """Compute the natural dedup/uniqueness key for a processed row (N7/Q4).

    The key matches each dataset's unique constraint (PLAN.md §4.1):
    ``items`` -> ``(item_number,)``; ``inventory`` ->
    ``(store_id, item_number, day)``; ``orderable-items`` /
    ``order-recommendations`` -> ``(store_id, item_number, ordering_day)``.

    Args:
        dataset: Which dataset ``values`` belongs to.
        values: Normalized column values, as produced in
            ``ProcessedRow.values`` by :func:`process_row`.

    Returns:
        A hashable tuple uniquely identifying the row's natural key.
    """
    raise NotImplementedError
