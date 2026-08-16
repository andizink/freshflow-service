"""Row-level quarantine rules Q1-Q5 and the dedup key function (PLAN.md §4.3).

This module is the single source of truth for which rows get rejected and
why (ADR §4.3), referenced by both tests and ``docs/DATA_QUALITY.md``.

It also owns the *normalization counter* vocabulary reported back to the
uploader (:data:`NORMALIZATION_KEYS`): the pure rules in
:mod:`app.ingest.normalize` know how to fix a value, this module decides
whether a fix actually happened and under which name it is counted.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.common.enums import DatasetKind, ReasonCode
from app.ingest.normalize import (
    INTEGER_PATTERN,
    TAG_SEPARATOR,
    coerce_item_number,
    normalize_category,
    normalize_store_id,
    normalize_tags,
    parse_day,
    parse_quantity,
)

#: N1 — a ``store_id`` was trimmed and/or lowercased.
STORE_ID_CLEANED = "store_id_cleaned"
#: N2 — an ``item_number`` was written as a zero-fractional float string.
ITEM_NUMBER_FLOAT_COERCED = "item_number_float_coerced"
#: N3 — a date arrived in ``DD/MM/YYYY`` form and was converted to ISO.
DATE_FORMAT_CONVERTED = "date_format_converted"
#: N5 — a value (other than ``store_id``/``category``, which have their own
#: counters) carried surrounding whitespace that was stripped.
VALUE_WHITESPACE_STRIPPED = "value_whitespace_stripped"
#: N4 — a category, tag, or ``is_bio`` literal was re-cased to canonical form.
CASING_NORMALIZED = "casing_normalized"

#: Every normalization counter name, in ingest-report order. The ingest
#: service uses this to zero-fill the report so absent keys never have to be
#: distinguished from zero counts by API clients (PLAN.md §3.1).
NORMALIZATION_KEYS: tuple[str, ...] = (
    STORE_ID_CLEANED,
    ITEM_NUMBER_FLOAT_COERCED,
    DATE_FORMAT_CONVERTED,
    VALUE_WHITESPACE_STRIPPED,
    CASING_NORMALIZED,
)

#: N6 — an inventory quantity had a non-zero fractional part. A warning, not
#: a rejection: the row loads with its exact value (ADR-008).
FRACTIONAL_QUANTITY = "fractional_quantity"

#: Accepted ``is_bio`` literals, matched case-insensitively.
_BOOLEAN_LITERALS = {"true": True, "false": False}

#: Canonical rendering of each boolean, used to detect casing repairs.
_CANONICAL_BOOLEAN = {True: "True", False: "False"}

#: Natural key columns per dataset, mirroring the unique constraints in
#: :mod:`app.models` (PLAN.md §4.1).
_KEY_COLUMNS: dict[DatasetKind, tuple[str, ...]] = {
    DatasetKind.ITEMS: ("item_number",),
    DatasetKind.INVENTORY: ("store_id", "item_number", "day"),
    DatasetKind.ORDERABLE_ITEMS: ("store_id", "item_number", "ordering_day"),
    DatasetKind.ORDER_RECOMMENDATIONS: ("store_id", "item_number", "ordering_day"),
}


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


@dataclass
class _RowContext:
    """Mutable accumulator for the findings gathered while processing one row.

    Attributes:
        reasons: Quarantine reasons in detection order, deduplicated — a
            row with two empty required columns is still one
            ``missing_field`` row in the report.
        normalizations: Per-name counts of repairs actually applied.
        warnings: Per-name counts of non-rejecting observations.
    """

    reasons: list[ReasonCode] = field(default_factory=list)
    normalizations: dict[str, int] = field(default_factory=dict)
    warnings: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: ReasonCode) -> None:
        """Record a quarantine reason, ignoring repeats of the same code.

        Args:
            reason: The reason code to record.
        """
        if reason not in self.reasons:
            self.reasons.append(reason)

    def count(self, name: str) -> None:
        """Count one applied normalization.

        Args:
            name: One of :data:`NORMALIZATION_KEYS`.
        """
        self.normalizations[name] = self.normalizations.get(name, 0) + 1

    def warn(self, name: str) -> None:
        """Count one non-rejecting warning.

        Args:
            name: The warning name, e.g. :data:`FRACTIONAL_QUANTITY`.
        """
        self.warnings[name] = self.warnings.get(name, 0) + 1


def _take(ctx: _RowContext, raw: dict[str, str], column: str) -> str | None:
    """Read a required column and strip it (N5), or reject the row (Q3).

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.
        column: The column to read.

    Returns:
        The stripped value, or ``None`` if the column was absent or blank
        (in which case ``missing_field`` has been recorded).
    """
    value = raw.get(column, "")
    text = value.strip()
    if not text:
        ctx.reject(ReasonCode.MISSING_FIELD)
        return None
    if text != value:
        ctx.count(VALUE_WHITESPACE_STRIPPED)
    return text


def _store_id(ctx: _RowContext, raw: dict[str, str]) -> str | None:
    """Read and normalize ``store_id`` (N1).

    Trimming and lowercasing are one repair with one counter
    (``store_id_cleaned``), because ``" STORE_A "`` is a single defect, not
    two.

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.

    Returns:
        The normalized store id, or ``None`` if the column was blank.
    """
    value = raw.get("store_id", "")
    normalized = normalize_store_id(value)
    if not normalized:
        ctx.reject(ReasonCode.MISSING_FIELD)
        return None
    if normalized != value:
        ctx.count(STORE_ID_CLEANED)
    return normalized


def _item_number(ctx: _RowContext, raw: dict[str, str]) -> int | None:
    """Read and coerce ``item_number`` (N2), rejecting the row on failure (Q3).

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.

    Returns:
        The integer item number, or ``None`` if it was blank or not
        coercible.
    """
    text = _take(ctx, raw, "item_number")
    if text is None:
        return None
    try:
        number = coerce_item_number(text)
    except ValueError:
        ctx.reject(ReasonCode.INVALID_VALUE)
        return None
    if "." in text:
        ctx.count(ITEM_NUMBER_FLOAT_COERCED)
    return number


def _day(ctx: _RowContext, raw: dict[str, str], column: str) -> date | None:
    """Read and parse a date column (N3), rejecting the row on failure (Q3).

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.
        column: The date column to read.

    Returns:
        The parsed date, or ``None`` if it was blank or unparseable.
    """
    text = _take(ctx, raw, column)
    if text is None:
        return None
    try:
        day = parse_day(text)
    except ValueError:
        ctx.reject(ReasonCode.INVALID_VALUE)
        return None
    if "/" in text:
        ctx.count(DATE_FORMAT_CONVERTED)
    return day


def _decimal(ctx: _RowContext, raw: dict[str, str], column: str) -> Decimal | None:
    """Read a required, non-negative decimal column, rejecting on failure (Q3).

    Negative money and stock values are ``invalid_value`` rather than Q1's
    ``negative_quantity``: Q1 is defined (PLAN.md §4.3) for
    ``recommended_quantity`` only, where a negative number is an actionable
    upstream forecasting bug rather than a corrupt cell.

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.
        column: The column to read.

    Returns:
        The exact decimal value, or ``None`` if it was blank, unparseable,
        or negative.
    """
    text = _take(ctx, raw, column)
    if text is None:
        return None
    try:
        value = parse_quantity(text)
    except ValueError:
        ctx.reject(ReasonCode.INVALID_VALUE)
        return None
    if value < 0:
        ctx.reject(ReasonCode.INVALID_VALUE)
        return None
    return value


def _optional_decimal(ctx: _RowContext, raw: dict[str, str], column: str) -> Decimal | None:
    """Read a nullable decimal column, rejecting only unparseable values (Q3).

    An empty cell is a legitimate ``NULL`` (the column is nullable in the
    ORM), not a missing required field. Negative values are allowed: a
    negative profit margin is a loss-leader, not corruption.

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.
        column: The column to read.

    Returns:
        The exact decimal value, or ``None`` if the cell was empty or
        unparseable.
    """
    value = raw.get(column, "")
    text = value.strip()
    if not text:
        return None
    if text != value:
        ctx.count(VALUE_WHITESPACE_STRIPPED)
    try:
        return parse_quantity(text)
    except ValueError:
        ctx.reject(ReasonCode.INVALID_VALUE)
        return None


def _strict_int(ctx: _RowContext, raw: dict[str, str], column: str) -> int | None:
    """Read a required, strictly integer-formatted column (Q3 on failure).

    Float-formatted values such as ``"12.0"`` are rejected rather than
    coerced, unlike ``item_number`` (N2). Profiling showed every
    ``recommended_quantity`` in the real file is a plain integer literal,
    so a decimal point here is evidence of an unexpected producer rather
    than the known, understood float-export defect that N2 repairs — and
    "order 12.4 pieces" has no single reasonable interpretation
    (DATA_GUIDE.md §3.4).

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.
        column: The column to read.

    Returns:
        The integer value, or ``None`` if it was blank or not a strict
        integer literal.
    """
    text = _take(ctx, raw, column)
    if text is None:
        return None
    if not INTEGER_PATTERN.match(text):
        ctx.reject(ReasonCode.INVALID_VALUE)
        return None
    return int(text)


def _is_bio(ctx: _RowContext, raw: dict[str, str]) -> bool | None:
    """Read the ``is_bio`` flag, accepting any casing of true/false (N4, Q3).

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.

    Returns:
        The boolean value, or ``None`` if the cell was blank or not a
        recognized boolean literal.
    """
    text = _take(ctx, raw, "is_bio")
    if text is None:
        return None
    value = _BOOLEAN_LITERALS.get(text.lower())
    if value is None:
        ctx.reject(ReasonCode.INVALID_VALUE)
        return None
    if text != _CANONICAL_BOOLEAN[value]:
        ctx.count(CASING_NORMALIZED)
    return value


def _category(ctx: _RowContext, raw: dict[str, str]) -> str | None:
    """Read and canonicalize ``category`` (N4).

    Any deviation from the canonical form counts once as
    ``casing_normalized``; whitespace on a category is not counted
    separately, because N4 canonicalization is one repair and counting it
    twice would inflate the report.

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.

    Returns:
        The canonical category name, or ``None`` if the cell was blank.
    """
    value = raw.get("category", "")
    normalized = normalize_category(value)
    if not normalized:
        ctx.reject(ReasonCode.MISSING_FIELD)
        return None
    if normalized != value:
        ctx.count(CASING_NORMALIZED)
    return normalized


def _tags(ctx: _RowContext, raw: dict[str, str]) -> list[str]:
    """Read and normalize the optional ``tags`` list (N4).

    Counting is per tag and split by defect kind, since the two are
    independent and both were measured in the real file: ``"new  "`` counts
    as ``value_whitespace_stripped``, ``"NEW"`` as ``casing_normalized``.
    Dropping duplicate or empty tags is not counted — nothing was repaired,
    a redundant token was removed.

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.

    Returns:
        The normalized tag list; empty when the cell is empty.
    """
    value = raw.get("tags", "")
    for token in value.split(TAG_SEPARATOR):
        stripped = token.strip()
        if not stripped:
            continue
        if stripped != token:
            ctx.count(VALUE_WHITESPACE_STRIPPED)
        if stripped != stripped.lower():
            ctx.count(CASING_NORMALIZED)
    return normalize_tags(value)


def _quantity(ctx: _RowContext, raw: dict[str, str]) -> Decimal | None:
    """Read an inventory quantity exactly, warning on fractions (N6, Q3).

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.

    Returns:
        The exact quantity, or ``None`` if it was blank, unparseable, or
        negative.
    """
    value = _decimal(ctx, raw, "quantity")
    if value is not None and value % 1 != 0:
        ctx.warn(FRACTIONAL_QUANTITY)
    return value


def _check_known_item(
    ctx: _RowContext, item_number: int | None, known_items: frozenset[int] | None
) -> None:
    """Apply Q2: reject rows referencing an item absent from the catalog.

    Skipped entirely when ``known_items`` is ``None`` (the catalog is not
    known, or the row *is* catalog) and when the item number did not parse
    (that is already an ``invalid_value``, and claiming an unparseable
    number is "unknown" would double-report one defect).

    Args:
        ctx: The accumulator for this row.
        item_number: The parsed item number, if any.
        known_items: The catalog item numbers, or ``None`` to skip.
    """
    if known_items is not None and item_number is not None and item_number not in known_items:
        ctx.reject(ReasonCode.UNKNOWN_ITEM)


def _check_date_order(
    ctx: _RowContext, ordering_day: date | None, delivery_day: date | None
) -> None:
    """Apply Q5: reject rows whose delivery precedes their ordering day.

    Only checked when both dates parsed; an unparseable date is already an
    ``invalid_value``.

    Args:
        ctx: The accumulator for this row.
        ordering_day: The parsed ordering day, if any.
        delivery_day: The parsed delivery day, if any.
    """
    if ordering_day is not None and delivery_day is not None and delivery_day < ordering_day:
        ctx.reject(ReasonCode.INVALID_DATE_ORDER)


def _build_items(
    ctx: _RowContext, raw: dict[str, str], known_items: frozenset[int] | None
) -> dict[str, object]:
    """Normalize one ``items`` row into :class:`~app.models.item.Item` values.

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.
        known_items: Catalog item numbers for Q2; normally ``None`` here,
            since this dataset *is* the catalog.

    Returns:
        Column values keyed as the ORM model expects.
    """
    item_number = _item_number(ctx, raw)
    _check_known_item(ctx, item_number, known_items)
    return {
        "item_number": item_number,
        "name": _take(ctx, raw, "name"),
        "category": _category(ctx, raw),
        "is_bio": _is_bio(ctx, raw),
        "purchase_price": _decimal(ctx, raw, "purchase_price"),
        "suggested_retail_price": _decimal(ctx, raw, "suggested_retail_price"),
    }


def _build_inventory(
    ctx: _RowContext, raw: dict[str, str], known_items: frozenset[int] | None
) -> dict[str, object]:
    """Normalize one ``inventory`` row into ORM values.

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.
        known_items: Catalog item numbers for Q2, or ``None`` to skip.

    Returns:
        Column values keyed as
        :class:`~app.models.inventory.InventoryRecord` expects.
    """
    item_number = _item_number(ctx, raw)
    _check_known_item(ctx, item_number, known_items)
    return {
        "store_id": _store_id(ctx, raw),
        "item_number": item_number,
        "day": _day(ctx, raw, "day"),
        "quantity": _quantity(ctx, raw),
    }


def _build_orderable_items(
    ctx: _RowContext, raw: dict[str, str], known_items: frozenset[int] | None
) -> dict[str, object]:
    """Normalize one ``orderable-items`` row into ORM values.

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.
        known_items: Catalog item numbers for Q2, or ``None`` to skip.

    Returns:
        Column values keyed as
        :class:`~app.models.orderable_item.OrderableItem` expects.
    """
    item_number = _item_number(ctx, raw)
    _check_known_item(ctx, item_number, known_items)
    ordering_day = _day(ctx, raw, "ordering_day")
    delivery_day = _day(ctx, raw, "delivery_day")
    _check_date_order(ctx, ordering_day, delivery_day)
    return {
        "store_id": _store_id(ctx, raw),
        "item_number": item_number,
        "ordering_day": ordering_day,
        "delivery_day": delivery_day,
        "purchase_price": _decimal(ctx, raw, "purchase_price"),
        "suggested_retail_price": _decimal(ctx, raw, "suggested_retail_price"),
        "profit_margin": _optional_decimal(ctx, raw, "profit_margin"),
        "tags": _tags(ctx, raw),
        "category": _category(ctx, raw),
    }


def _build_order_recommendations(
    ctx: _RowContext, raw: dict[str, str], known_items: frozenset[int] | None
) -> dict[str, object]:
    """Normalize one ``order-recommendations`` row into ORM values.

    Applies Q1 (``negative_quantity``) to ``recommended_quantity``.

    Args:
        ctx: The accumulator for this row.
        raw: The raw row.
        known_items: Catalog item numbers for Q2, or ``None`` to skip.

    Returns:
        Column values keyed as
        :class:`~app.models.order_recommendation.OrderRecommendation`
        expects.
    """
    item_number = _item_number(ctx, raw)
    _check_known_item(ctx, item_number, known_items)
    ordering_day = _day(ctx, raw, "ordering_day")
    delivery_day = _day(ctx, raw, "delivery_day")
    _check_date_order(ctx, ordering_day, delivery_day)
    quantity = _strict_int(ctx, raw, "recommended_quantity")
    if quantity is not None and quantity < 0:
        ctx.reject(ReasonCode.NEGATIVE_QUANTITY)
    return {
        "store_id": _store_id(ctx, raw),
        "item_number": item_number,
        "ordering_day": ordering_day,
        "delivery_day": delivery_day,
        "recommended_quantity": quantity,
    }


_Builder = Callable[[_RowContext, dict[str, str], frozenset[int] | None], dict[str, object]]

#: Per-dataset normalizers. A table rather than a ``match`` so that adding a
#: dataset is a one-line change with no unreachable fallback branch.
_BUILDERS: dict[DatasetKind, _Builder] = {
    DatasetKind.ITEMS: _build_items,
    DatasetKind.INVENTORY: _build_inventory,
    DatasetKind.ORDERABLE_ITEMS: _build_orderable_items,
    DatasetKind.ORDER_RECOMMENDATIONS: _build_order_recommendations,
}


def process_row(
    dataset: DatasetKind,
    raw: dict[str, str],
    known_items: frozenset[int] | None,
) -> ProcessedRow:
    """Normalize and validate one raw row for ``dataset``.

    Applies normalization rules N1-N6 (via :mod:`app.ingest.normalize`) and
    quarantine rules Q1, Q2, Q3, Q5 (Q4 - conflicting duplicates - is
    detected across rows by the caller using :func:`key_for`, not here).

    Every applicable rule is evaluated: a row that is both missing a field
    and referencing an unknown item comes back with both reasons, so one
    ingest report tells the uploader everything wrong with the row rather
    than only the first defect found. Reasons are deduplicated and returned
    in detection order.

    Counters describe **loaded rows only**. A quarantined row returns empty
    ``normalizations`` and ``warnings``: the report's normalization totals
    answer "what did you change about the data you kept?", and counting
    repairs on rows that were then thrown away would make those totals
    unreconcilable with the loaded data. Counters count *values*, not rows —
    two stripped cells in one row count twice — which matters only for
    ``value_whitespace_stripped`` and ``casing_normalized``, the two
    counters that can apply to several columns of the same row.

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
    ctx = _RowContext()
    values = _BUILDERS[dataset](ctx, raw, known_items)
    if ctx.reasons:
        return ProcessedRow(values=None, reasons=tuple(ctx.reasons))
    return ProcessedRow(
        values=values,
        normalizations=ctx.normalizations,
        warnings=ctx.warnings,
    )


def key_for(dataset: DatasetKind, values: dict[str, object]) -> tuple[object, ...]:
    """Compute the natural dedup/uniqueness key for a processed row (N7/Q4).

    The key matches each dataset's unique constraint (PLAN.md §4.1):
    ``items`` -> ``(item_number,)``; ``inventory`` ->
    ``(store_id, item_number, day)``; ``orderable-items`` /
    ``order-recommendations`` -> ``(store_id, item_number, ordering_day)``.

    Two rows sharing a key are duplicates: identical payloads collapse
    silently and are counted (N7), differing payloads are a
    ``conflicting_duplicate`` (Q4). Both comparisons happen on *normalized*
    values, so ``" STORE_A "`` and ``store_a`` are recognized as the same
    key rather than slipping past as two.

    Args:
        dataset: Which dataset ``values`` belongs to.
        values: Normalized column values, as produced in
            ``ProcessedRow.values`` by :func:`process_row`.

    Returns:
        A hashable tuple uniquely identifying the row's natural key.
    """
    return tuple(values[column] for column in _KEY_COLUMNS[dataset])
