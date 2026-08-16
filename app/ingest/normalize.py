"""Pure normalization functions, rules N1-N7 (PLAN.md §4.2).

Each function implements exactly one normalization rule and cites its rule
ID in its docstring, so code, tests, and ``docs/DATA_QUALITY.md`` stay
traceable to the same rule table. Functions are pure: no I/O, no exceptions
beyond ``ValueError`` for genuinely unparseable input (callers in
``app.ingest.rules`` decide whether that becomes a quarantine reason).
"""

from datetime import date
from decimal import Decimal


def normalize_store_id(raw: str) -> str:
    """Normalize a store identifier (N1): strip whitespace, lowercase.

    Example: ``" STORE_A "`` -> ``"store_a"``.

    Args:
        raw: The raw store identifier as read from a CSV cell.

    Returns:
        The stripped, lowercased store identifier.
    """
    raise NotImplementedError


def coerce_item_number(raw: str) -> int:
    """Coerce an item number to ``int`` (N2).

    Accepts plain integer strings (``"1001"``) and float-formatted strings
    whose fractional part is exactly zero (``"1001.0"`` -> ``1001``).
    Any other fractional value (e.g. ``"1001.5"``) is not coercible.

    Args:
        raw: The raw item number as read from a CSV cell.

    Returns:
        The coerced integer item number.

    Raises:
        ValueError: If ``raw`` is not an integer or zero-fractional float
            string.
    """
    raise NotImplementedError


def parse_day(raw: str) -> date:
    """Parse a date string (N3): try ISO ``YYYY-MM-DD``, then day-first ``DD/MM/YYYY``.

    Day-first slash-date interpretation is proven by unambiguous values
    found in profiling (e.g. ``23/01/2024``, ``31/12/2024``) — see ADR-007.

    Args:
        raw: The raw date string as read from a CSV cell.

    Returns:
        The parsed :class:`datetime.date`.

    Raises:
        ValueError: If ``raw`` matches neither accepted format.
    """
    raise NotImplementedError


def normalize_category(raw: str) -> str:
    """Normalize a category name (N4): strip whitespace, canonical casing.

    Example: ``"  FRUITS"`` / ``"fruits"`` -> ``"Fruits"``.

    Args:
        raw: The raw category string as read from a CSV cell.

    Returns:
        The stripped, canonically-cased category name.
    """
    raise NotImplementedError


def normalize_tags(raw: str) -> list[str]:
    """Normalize a tag list (N4): split, strip, lowercase, dedupe.

    Example: ``"new, NEW, ON_SALE"`` -> ``["new", "on_sale"]``.

    Args:
        raw: The raw, delimiter-separated tags string as read from a CSV
            cell.

    Returns:
        The deduplicated, lowercased, whitespace-stripped tag list, order
        preserved by first occurrence.
    """
    raise NotImplementedError


def strip_text(raw: str) -> str:
    """Strip surrounding whitespace from a free-text field (N5).

    Args:
        raw: The raw text value as read from a CSV cell.

    Returns:
        ``raw`` with leading and trailing whitespace removed.
    """
    raise NotImplementedError


def parse_quantity(raw: str) -> Decimal:
    """Parse an inventory quantity as an exact :class:`~decimal.Decimal` (N6).

    Fractional quantities (e.g. ``"16.4"``) are preserved exactly, not
    rounded — they are plausible weight-based measurements despite the
    dataset's pieces convention (ADR-008); rounding for display happens
    only at the API layer.

    Args:
        raw: The raw quantity string as read from a CSV cell.

    Returns:
        The parsed exact quantity.

    Raises:
        ValueError: If ``raw`` is not a valid decimal number.
    """
    raise NotImplementedError
