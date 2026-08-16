"""Streaming CSV reading and header validation for ingest (PLAN.md §5, ADR-005).

Uses the stdlib ``csv`` module in streaming mode (not pandas) so memory
stays flat regardless of file size and every row can be attributed to its
exact source line number in the ingest report.
"""

import csv
from collections.abc import Iterator
from typing import IO

from app.common.enums import DatasetKind

#: Encoding used to decode uploaded CSVs. ``utf-8-sig`` is plain UTF-8 that
#: additionally tolerates (and discards) a leading byte-order mark, which
#: spreadsheet exports frequently prepend.
ENCODING = "utf-8-sig"

#: Expected CSV header columns per dataset, in the order the challenge
#: files use them (PLAN.md §1.1, §4.1). Header validation compares the
#: parsed header row against these tuples (order-insensitive membership
#: check is a parser implementation detail, not part of this contract).
REQUIRED_HEADERS: dict[DatasetKind, tuple[str, ...]] = {
    DatasetKind.ITEMS: (
        "item_number",
        "name",
        "category",
        "is_bio",
        "purchase_price",
        "suggested_retail_price",
    ),
    DatasetKind.INVENTORY: (
        "store_id",
        "item_number",
        "day",
        "quantity",
    ),
    DatasetKind.ORDERABLE_ITEMS: (
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
    DatasetKind.ORDER_RECOMMENDATIONS: (
        "store_id",
        "item_number",
        "ordering_day",
        "delivery_day",
        "recommended_quantity",
    ),
}


class HeaderError(ValueError):
    """Raised when a CSV's header row does not match the expected columns.

    Attributes:
        expected: The header columns required for the target dataset.
        found: The header columns actually present in the uploaded file.
    """

    def __init__(self, expected: tuple[str, ...], found: tuple[str, ...]) -> None:
        """Initialize the error with the expected and found header tuples.

        Args:
            expected: The header columns required for the target dataset.
            found: The header columns actually present in the uploaded file.
        """
        self.expected = expected
        self.found = found
        super().__init__(f"CSV header mismatch: expected columns {expected!r}, found {found!r}")


def _decoded_lines(file: IO[bytes]) -> Iterator[str]:
    """Decode a binary stream to text lines without taking ownership of it.

    Deliberately avoids :class:`io.TextIOWrapper`: a wrapper closes the
    underlying binary stream when it is garbage collected, which would
    close the caller's upload file mid-request if the returned generator is
    abandoned before exhaustion. Splitting on newlines is safe for UTF-8
    because no continuation byte can equal ``0x0A``, and :mod:`csv` handles
    quoted fields that span several of these lines.

    Args:
        file: A binary file-like object positioned at the start of the CSV.

    Yields:
        The file's contents, decoded with :data:`ENCODING`, one line at a
        time.
    """
    for line in file:
        yield line.decode(ENCODING)


def read_rows(file: IO[bytes], dataset: DatasetKind) -> Iterator[tuple[int, dict[str, str]]]:
    """Stream CSV rows from ``file`` as ``(row_number, raw_row)`` pairs.

    Validates the header row against :data:`REQUIRED_HEADERS` before
    yielding any data rows. The comparison is order-insensitive (columns
    may appear in any order) but otherwise exact: a missing, extra,
    misspelled, or duplicated column is a :class:`HeaderError`, as is an
    empty file (no header row at all).

    Every yielded row carries exactly the keys of
    ``REQUIRED_HEADERS[dataset]``: cells missing from a short row become
    ``""`` (rather than :mod:`csv`'s ``None``) so downstream rules only
    ever see strings, and cells beyond the declared header are dropped.

    Args:
        file: A binary file-like object positioned at the start of the CSV.
        dataset: Which dataset's expected header to validate against.

    Yields:
        Tuples of ``(row_number, raw_row)`` where ``row_number`` is
        1-indexed with the header counted as row 1 (so the first data row
        is row 2), and ``raw_row`` maps header names to their raw string
        values, unmodified.

    Raises:
        HeaderError: If the CSV header does not match
            ``REQUIRED_HEADERS[dataset]``.
    """
    expected = REQUIRED_HEADERS[dataset]
    reader = csv.DictReader(_decoded_lines(file))
    found = tuple(reader.fieldnames or ())
    if sorted(found) != sorted(expected):
        raise HeaderError(expected, found)
    for row_number, row in enumerate(reader, start=2):
        raw_row: dict[str, str] = {}
        for column in expected:
            value = row.get(column)
            raw_row[column] = value if isinstance(value, str) else ""
        yield row_number, raw_row
