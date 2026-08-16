"""Streaming CSV reading and header validation for ingest (PLAN.md §5, ADR-005).

Uses the stdlib ``csv`` module in streaming mode (not pandas) so memory
stays flat regardless of file size and every row can be attributed to its
exact source line number in the ingest report.
"""

from collections.abc import Iterator
from typing import IO

from app.common.enums import DatasetKind

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


def read_rows(file: IO[bytes], dataset: DatasetKind) -> Iterator[tuple[int, dict[str, str]]]:
    """Stream CSV rows from ``file`` as ``(row_number, raw_row)`` pairs.

    Validates the header row against :data:`REQUIRED_HEADERS` before
    yielding any data rows.

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
    raise NotImplementedError
