#!/usr/bin/env python3
"""Independently re-derive expected ingest report numbers for the real data.

This is a **standalone** profiling script: it deliberately does not import
anything from ``app/``. Its job is to re-implement the documented
normalization rules (N1-N7) and quarantine rules (Q1-Q5) from
``docs/DATA_QUALITY.md`` / ``docs/PROBLEM_ANALYSIS.md`` / the service and
rules docstrings from scratch, then walk the four real challenge CSVs in
``data/`` the same way ``app.ingest.service.ingest_dataset`` walks an
uploaded file, and write the resulting counts to
``tests/e2e/expected_counts.json``.

The point of writing this a second time, independently, is that the
"expected" numbers used by ``tests/e2e/test_real_data.py`` are derived
twice by two different pieces of code (this script and the service under
test) rather than copied from one to the other. Where this script's output
disagrees with the service, that is a finding to investigate and report,
not something to quietly reconcile by copying the service's numbers here.

Bookkeeping semantics this script reproduces (see ``app/ingest/service.py``
module docstring for the authoritative description):

* Every received row lands in exactly one of three buckets: loaded (first
  row seen for its natural key, among rows that passed Q1-Q3/Q5),
  deduplicated (N7: a later row with the same key and an identical
  normalized payload as the row already loaded for that key), or rejected
  (either failed Q1-Q3/Q5 outright, or is a later row with the same key as
  an already-loaded row but a *different* payload - Q4 conflicting
  duplicate).
* ``quarantined_rows`` is *not* simply the rejected-row count when Q4
  occurs: for every key with at least one conflicting duplicate, the
  already-loaded first occurrence's raw row is *also* archived to
  quarantine (so both the accepted and the conflicting version are
  auditable) - intentional double bookkeeping, not a bug.
* Normalization and warning counters are accumulated for every row that
  passes Q1-Q3/Q5 (i.e. is not quarantined outright), *before* the
  dedup/Q4 decision is made for that row - so a normalization applied to a
  row that later turns out to be an exact duplicate (N7, dropped) or a
  conflicting duplicate (Q4, quarantined) is still counted. Only rows
  quarantined outright (Q1/Q2/Q3/Q5) contribute zero normalizations and
  warnings. This mirrors ``app.ingest.service.ingest_dataset``, which
  merges ``processed.normalizations``/``processed.warnings`` into the
  running totals unconditionally, before the dedup/Q4 branch runs.

Usage:
    uv run python scripts/generate_expected_counts.py

Writes ``tests/e2e/expected_counts.json``.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_PATH = ROOT / "tests" / "e2e" / "expected_counts.json"

#: File encoding used to read the CSVs, matching ``app.ingest.parser`` (a
#: BOM-tolerant UTF-8 variant, since spreadsheet exports commonly prepend
#: one).
ENCODING = "utf-8-sig"

# --- Independently authored regex patterns (own copies; not imported) -----

_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLASH_DAY_FORMAT = "%d/%m/%Y"
_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")
_DECIMAL_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_TAG_SEPARATOR = ","

_BOOLEAN_LITERALS = {"true": True, "false": False}
_CANONICAL_BOOLEAN = {True: "True", False: "False"}

# --- Per-dataset configuration ---------------------------------------------

EXPECTED_HEADERS: dict[str, tuple[str, ...]] = {
    "items": (
        "item_number",
        "name",
        "category",
        "is_bio",
        "purchase_price",
        "suggested_retail_price",
    ),
    "inventory": ("store_id", "item_number", "day", "quantity"),
    "orderable-items": (
        "store_id",
        "item_number",
        "ordering_day",
        "delivery_day",
        "purchase_price",
        "suggested_retail_price",
        "profit_margin",
        "tags",
        "category",
    ),
    "order-recommendations": (
        "store_id",
        "item_number",
        "ordering_day",
        "delivery_day",
        "recommended_quantity",
    ),
}

#: Natural dedup/uniqueness key columns per dataset (PLAN.md §4.1).
KEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "items": ("item_number",),
    "inventory": ("store_id", "item_number", "day"),
    "orderable-items": ("store_id", "item_number", "ordering_day"),
    "order-recommendations": ("store_id", "item_number", "ordering_day"),
}

#: Source CSV filename per dataset key.
SOURCE_FILE: dict[str, str] = {
    "items": "items.csv",
    "inventory": "inventory.csv",
    "orderable-items": "orderable_items.csv",
    "order-recommendations": "order_recommendations.csv",
}

#: Ingest order: items first (so the catalog exists for the Q2 check
#: against the other three), matching ``scripts/load_all.sh`` and
#: ``tests/e2e/test_real_data.py``.
DATASET_ORDER: tuple[str, ...] = (
    "items",
    "inventory",
    "orderable-items",
    "order-recommendations",
)


@dataclass
class _RowContext:
    """Accumulator for one row's quarantine reasons, normalizations, warnings."""

    reasons: list[str] = field(default_factory=list)
    normalizations: dict[str, int] = field(default_factory=dict)
    warnings: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        """Record a quarantine reason, ignoring repeats of the same code."""
        if reason not in self.reasons:
            self.reasons.append(reason)

    def count(self, name: str) -> None:
        """Count one applied normalization."""
        self.normalizations[name] = self.normalizations.get(name, 0) + 1

    def warn(self, name: str) -> None:
        """Count one non-rejecting warning."""
        self.warnings[name] = self.warnings.get(name, 0) + 1


# --- Field-level readers (each mirrors one N-rule / Q-rule) ---------------


def _take_required(ctx: _RowContext, raw: dict[str, str], column: str) -> str | None:
    """Read a required free-text column, stripped (N5); reject if blank (Q3)."""
    value = raw.get(column, "")
    text = value.strip()
    if not text:
        ctx.reject("missing_field")
        return None
    if text != value:
        ctx.count("value_whitespace_stripped")
    return text


def _store_id(ctx: _RowContext, raw: dict[str, str]) -> str | None:
    """Read and normalize ``store_id`` (N1): strip + lowercase, one counter."""
    value = raw.get("store_id", "")
    normalized = value.strip().lower()
    if not normalized:
        ctx.reject("missing_field")
        return None
    if normalized != value:
        ctx.count("store_id_cleaned")
    return normalized


def _item_number(ctx: _RowContext, raw: dict[str, str]) -> int | None:
    """Read and coerce ``item_number`` (N2): int, or zero-fractional float string."""
    text = _take_required(ctx, raw, "item_number")
    if text is None:
        return None
    if _INTEGER_PATTERN.match(text):
        return int(text)
    if not _DECIMAL_PATTERN.match(text):
        ctx.reject("invalid_value")
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        ctx.reject("invalid_value")
        return None
    if number != number.to_integral_value():
        ctx.reject("invalid_value")
        return None
    ctx.count("item_number_float_coerced")
    return int(number)


def _day(ctx: _RowContext, raw: dict[str, str], column: str) -> date | None:
    """Read and parse a date column (N3): ISO first, then day-first slash form."""
    text = _take_required(ctx, raw, column)
    if text is None:
        return None
    if _ISO_DAY.match(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            ctx.reject("invalid_value")
            return None
    try:
        parsed = datetime.strptime(text, _SLASH_DAY_FORMAT).date()
    except ValueError:
        ctx.reject("invalid_value")
        return None
    ctx.count("date_format_converted")
    return parsed


def _decimal_required(ctx: _RowContext, raw: dict[str, str], column: str) -> Decimal | None:
    """Read a required, non-negative exact decimal column."""
    text = _take_required(ctx, raw, column)
    if text is None:
        return None
    if not _DECIMAL_PATTERN.match(text):
        ctx.reject("invalid_value")
        return None
    value = Decimal(text)
    if value < 0:
        ctx.reject("invalid_value")
        return None
    return value


def _decimal_optional(ctx: _RowContext, raw: dict[str, str], column: str) -> Decimal | None:
    """Read a nullable decimal column (blank -> ``None``; negatives allowed)."""
    value = raw.get(column, "")
    text = value.strip()
    if not text:
        return None
    if text != value:
        ctx.count("value_whitespace_stripped")
    if not _DECIMAL_PATTERN.match(text):
        ctx.reject("invalid_value")
        return None
    return Decimal(text)


def _strict_int(ctx: _RowContext, raw: dict[str, str], column: str) -> int | None:
    """Read a required, strictly-integer-literal column (no float coercion)."""
    text = _take_required(ctx, raw, column)
    if text is None:
        return None
    if not _INTEGER_PATTERN.match(text):
        ctx.reject("invalid_value")
        return None
    return int(text)


def _is_bio(ctx: _RowContext, raw: dict[str, str]) -> bool | None:
    """Read ``is_bio`` (N4): any casing of true/false accepted."""
    text = _take_required(ctx, raw, "is_bio")
    if text is None:
        return None
    value = _BOOLEAN_LITERALS.get(text.lower())
    if value is None:
        ctx.reject("invalid_value")
        return None
    if text != _CANONICAL_BOOLEAN[value]:
        ctx.count("casing_normalized")
    return value


def _category(ctx: _RowContext, raw: dict[str, str]) -> str | None:
    """Read and canonicalize ``category`` (N4): strip + title-first-letter casing."""
    value = raw.get("category", "")
    normalized = value.strip().capitalize()
    if not normalized:
        ctx.reject("missing_field")
        return None
    if normalized != value:
        ctx.count("casing_normalized")
    return normalized


def _tags(ctx: _RowContext, raw: dict[str, str]) -> list[str]:
    """Read and normalize the optional ``tags`` list (N4): split/strip/lower/dedupe."""
    value = raw.get("tags", "")
    seen: set[str] = set()
    tags: list[str] = []
    for token in value.split(_TAG_SEPARATOR):
        stripped = token.strip()
        if not stripped:
            continue
        if stripped != token:
            ctx.count("value_whitespace_stripped")
        lowered = stripped.lower()
        if stripped != lowered:
            ctx.count("casing_normalized")
        if lowered not in seen:
            seen.add(lowered)
            tags.append(lowered)
    return tags


def _quantity(ctx: _RowContext, raw: dict[str, str]) -> Decimal | None:
    """Read an inventory quantity exactly (N6), warning (not rejecting) on fractions."""
    value = _decimal_required(ctx, raw, "quantity")
    if value is not None and value % 1 != 0:
        ctx.warn("fractional_quantity")
    return value


def _check_known_item(
    ctx: _RowContext, item_number: int | None, known_items: frozenset[int] | None
) -> None:
    """Apply Q2: reject rows referencing an item absent from the catalog."""
    if known_items is not None and item_number is not None and item_number not in known_items:
        ctx.reject("unknown_item")


def _check_date_order(
    ctx: _RowContext, ordering_day: date | None, delivery_day: date | None
) -> None:
    """Apply Q5: reject rows whose delivery precedes their ordering day."""
    if ordering_day is not None and delivery_day is not None and delivery_day < ordering_day:
        ctx.reject("invalid_date_order")


# --- Per-dataset row builders -----------------------------------------------


def _build_items(
    ctx: _RowContext, raw: dict[str, str], known_items: frozenset[int] | None
) -> dict[str, Any]:
    item_number = _item_number(ctx, raw)
    _check_known_item(ctx, item_number, known_items)
    return {
        "item_number": item_number,
        "name": _take_required(ctx, raw, "name"),
        "category": _category(ctx, raw),
        "is_bio": _is_bio(ctx, raw),
        "purchase_price": _decimal_required(ctx, raw, "purchase_price"),
        "suggested_retail_price": _decimal_required(ctx, raw, "suggested_retail_price"),
    }


def _build_inventory(
    ctx: _RowContext, raw: dict[str, str], known_items: frozenset[int] | None
) -> dict[str, Any]:
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
) -> dict[str, Any]:
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
        "purchase_price": _decimal_required(ctx, raw, "purchase_price"),
        "suggested_retail_price": _decimal_required(ctx, raw, "suggested_retail_price"),
        "profit_margin": _decimal_optional(ctx, raw, "profit_margin"),
        "tags": _tags(ctx, raw),
        "category": _category(ctx, raw),
    }


def _build_order_recommendations(
    ctx: _RowContext, raw: dict[str, str], known_items: frozenset[int] | None
) -> dict[str, Any]:
    item_number = _item_number(ctx, raw)
    _check_known_item(ctx, item_number, known_items)
    ordering_day = _day(ctx, raw, "ordering_day")
    delivery_day = _day(ctx, raw, "delivery_day")
    _check_date_order(ctx, ordering_day, delivery_day)
    quantity = _strict_int(ctx, raw, "recommended_quantity")
    if quantity is not None and quantity < 0:
        ctx.reject("negative_quantity")
    return {
        "store_id": _store_id(ctx, raw),
        "item_number": item_number,
        "ordering_day": ordering_day,
        "delivery_day": delivery_day,
        "recommended_quantity": quantity,
    }


_BUILDERS = {
    "items": _build_items,
    "inventory": _build_inventory,
    "orderable-items": _build_orderable_items,
    "order-recommendations": _build_order_recommendations,
}


def process_row(
    dataset: str, raw: dict[str, str], known_items: frozenset[int] | None
) -> tuple[dict[str, Any] | None, list[str], dict[str, int], dict[str, int]]:
    """Normalize and validate one raw row for ``dataset``.

    Returns:
        A ``(values, reasons, normalizations, warnings)`` tuple: ``values``
        is ``None`` when the row was quarantined outright (Q1-Q3/Q5), in
        which case ``normalizations``/``warnings`` are always empty,
        matching ``app.ingest.rules.process_row``.
    """
    ctx = _RowContext()
    values = _BUILDERS[dataset](ctx, raw, known_items)
    if ctx.reasons:
        return None, ctx.reasons, {}, {}
    return values, [], ctx.normalizations, ctx.warnings


def key_for(dataset: str, values: dict[str, Any]) -> tuple[Any, ...]:
    """Compute the natural dedup/uniqueness key for a processed row."""
    return tuple(values[column] for column in KEY_COLUMNS[dataset])


def _merge_counts(total: dict[str, int], delta: dict[str, int]) -> None:
    for key, value in delta.items():
        total[key] = total.get(key, 0) + value


def _read_raw_rows(path: Path, dataset: str) -> list[dict[str, str]]:
    """Read all data rows of ``path`` as raw string dicts, header-validated."""
    expected = EXPECTED_HEADERS[dataset]
    with path.open(newline="", encoding=ENCODING) as handle:
        reader = csv.DictReader(handle)
        found = tuple(reader.fieldnames or ())
        if sorted(found) != sorted(expected):
            raise ValueError(f"{path}: header mismatch, expected {expected!r}, found {found!r}")
        rows = []
        for row in reader:
            raw_row = {column: row.get(column) or "" for column in expected}
            rows.append(raw_row)
        return rows


def profile_dataset(
    dataset: str, path: Path, known_items: frozenset[int] | None
) -> tuple[dict[str, Any], frozenset[int] | None]:
    """Independently derive the expected ``IngestReport`` fields for one CSV.

    Mirrors ``app.ingest.service.ingest_dataset``'s received/loaded/
    deduplicated/quarantined bookkeeping (see module docstring), but reads
    straight from ``path`` with the stdlib ``csv`` module rather than the
    service under test.

    Args:
        dataset: The dataset key (matches the API path segment).
        path: The source CSV file.
        known_items: The catalog item numbers loaded so far (``None`` for
            the ``items`` dataset itself, which defines the catalog).

    Returns:
        A ``(report_fields, loaded_item_numbers)`` tuple. ``loaded_item_numbers``
        is the frozenset of item numbers loaded by this run when
        ``dataset == "items"`` (for use as the next dataset's
        ``known_items``), else ``None``.
    """
    received_rows = 0
    normalizations: dict[str, int] = {}
    quarantine_summary: dict[str, int] = {}
    quarantined_rows = 0

    seen: dict[tuple[Any, ...], tuple[dict[str, Any]]] = {}
    loaded_order: list[tuple[Any, ...]] = []
    conflict_flagged: set[tuple[Any, ...]] = set()
    deduplicated_rows = 0

    for raw_row in _read_raw_rows(path, dataset):
        received_rows += 1
        values, reasons, norm, _warnings = process_row(dataset, raw_row, known_items)
        _merge_counts(normalizations, norm)

        if values is None:
            quarantined_rows += 1
            for reason in reasons:
                quarantine_summary[reason] = quarantine_summary.get(reason, 0) + 1
            continue

        key = key_for(dataset, values)
        if key not in seen:
            seen[key] = (values,)
            loaded_order.append(key)
            continue

        (first_values,) = seen[key]
        if values == first_values:
            deduplicated_rows += 1
            continue

        # Q4: conflicting duplicate. First occurrence stays loaded; both its
        # raw row and this row's raw row are archived to quarantine -
        # that's two additional quarantine entries for one already-loaded
        # key the first time a conflict for that key is seen, then one more
        # per further conflicting row.
        if key not in conflict_flagged:
            conflict_flagged.add(key)
            quarantined_rows += 1
            quarantine_summary["conflicting_duplicate"] = (
                quarantine_summary.get("conflicting_duplicate", 0) + 1
            )
        quarantined_rows += 1
        quarantine_summary["conflicting_duplicate"] = (
            quarantine_summary.get("conflicting_duplicate", 0) + 1
        )

    loaded_rows = len(loaded_order)

    report_fields = {
        "received_rows": received_rows,
        "loaded_rows": loaded_rows,
        "deduplicated_rows": deduplicated_rows,
        "quarantined_rows": quarantined_rows,
        "normalizations": dict(sorted(normalizations.items())),
        "quarantine_summary": dict(sorted(quarantine_summary.items())),
    }

    loaded_item_numbers: frozenset[int] | None = None
    if dataset == "items":
        loaded_item_numbers = frozenset(seen[key][0]["item_number"] for key in loaded_order)

    return report_fields, loaded_item_numbers


def main() -> None:
    """Profile all four real data files and write ``expected_counts.json``."""
    known_items: frozenset[int] | None = None
    results: dict[str, Any] = {}

    for dataset in DATASET_ORDER:
        path = DATA_DIR / SOURCE_FILE[dataset]
        report_fields, loaded_item_numbers = profile_dataset(dataset, path, known_items)
        results[dataset] = report_fields
        if dataset == "items":
            known_items = loaded_item_numbers

        print(
            f"{dataset}: received={report_fields['received_rows']} "
            f"loaded={report_fields['loaded_rows']} "
            f"deduplicated={report_fields['deduplicated_rows']} "
            f"quarantined={report_fields['quarantined_rows']}"
        )
        if report_fields["quarantine_summary"]:
            print(f"  quarantine_summary={report_fields['quarantine_summary']}")
        if report_fields["normalizations"]:
            print(f"  normalizations={report_fields['normalizations']}")

    output = {
        "_note": (
            "Generated by scripts/generate_expected_counts.py — an independent, "
            "standalone (stdlib-only, no app/ import) re-derivation of the "
            "documented N1-N7/Q1-Q5 rules, run against the real data/ CSVs in "
            "items -> inventory -> orderable-items -> order-recommendations "
            "order. Do not hand-edit; re-run the script instead. See PLAN.md "
            "§6.1 and docs/DATA_QUALITY.md."
        ),
        **results,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, sort_keys=False) + "\n")
    print(f"\nwrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
