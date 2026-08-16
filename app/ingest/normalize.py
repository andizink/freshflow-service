"""Pure normalization functions, rules N1-N7 (PLAN.md §4.2).

Each function implements exactly one normalization rule and cites its rule
ID in its docstring, so code, tests, and ``docs/DATA_QUALITY.md`` stay
traceable to the same rule table. Functions are pure: no I/O, no exceptions
beyond ``ValueError`` for genuinely unparseable input (callers in
``app.ingest.rules`` decide whether that becomes a quarantine reason).
"""

import re
from datetime import date, datetime
from decimal import Decimal

#: Strict ISO calendar-date pattern. ``date.fromisoformat`` also accepts
#: basic (``20240123``) and week (``2024-W01-1``) forms; the contract
#: (PLAN.md §4.2 N3) is ``YYYY-MM-DD`` only, so the input is screened first.
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Day-first slash format, proven by ``23/01/2024`` / ``31/12/2024`` in the
#: real data (ADR-007).
_SLASH_DAY_FORMAT = "%d/%m/%Y"

#: Tag list separator used by ``orderable_items.tags``.
TAG_SEPARATOR = ","

#: A strict integer literal: optional sign, digits only. Deliberately
#: narrower than :func:`int`, which also accepts underscore separators
#: (``int("1_2") == 12``) — silently reading a typo as a different number
#: is exactly the kind of invented data these rules exist to prevent.
INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")

#: A decimal literal: optional sign, digits with optional fraction and
#: exponent. Like :data:`INTEGER_PATTERN` this is narrower than the
#: constructor it guards — :class:`~decimal.Decimal` also accepts
#: underscores (``Decimal("1_2") == 12``) and the special values ``NaN``
#: and ``Infinity``, none of which are meaningful in a CSV cell.
DECIMAL_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def normalize_store_id(raw: str) -> str:
    """Normalize a store identifier (N1): strip whitespace, lowercase.

    Example: ``" STORE_A "`` -> ``"store_a"``.

    Args:
        raw: The raw store identifier as read from a CSV cell.

    Returns:
        The stripped, lowercased store identifier.
    """
    return raw.strip().lower()


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
    text = raw.strip()
    if INTEGER_PATTERN.match(text):
        return int(text)
    if not DECIMAL_PATTERN.match(text):
        raise ValueError(f"item_number is not a number: {raw!r}")
    number = Decimal(text)
    if number != number.to_integral_value():
        raise ValueError(f"item_number has a non-zero fractional part: {raw!r}")
    return int(number)


def parse_day(raw: str) -> date:
    """Parse a date string (N3): try ISO ``YYYY-MM-DD``, then day-first ``DD/MM/YYYY``.

    Day-first slash-date interpretation is proven by unambiguous values
    found in profiling (e.g. ``23/01/2024``, ``31/12/2024``) — see ADR-007.

    ISO parsing is deliberately stricter than :meth:`date.fromisoformat`,
    which since Python 3.11 also accepts basic (``20240123``) and week
    (``2024-W01-1``) forms: only ``YYYY-MM-DD`` is accepted here, so an
    unexpected shape is quarantined rather than silently reinterpreted.
    Datetime strings (``2024-01-23T00:00:00``) are rejected for the same
    reason.

    Args:
        raw: The raw date string as read from a CSV cell.

    Returns:
        The parsed :class:`datetime.date`.

    Raises:
        ValueError: If ``raw`` matches neither accepted format.
    """
    text = raw.strip()
    message = f"date is not a valid YYYY-MM-DD or DD/MM/YYYY value: {raw!r}"
    if _ISO_DAY.match(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise ValueError(message) from None
    try:
        return datetime.strptime(text, _SLASH_DAY_FORMAT).date()
    except ValueError:
        raise ValueError(message) from None


def normalize_category(raw: str) -> str:
    """Normalize a category name (N4): strip whitespace, canonical casing.

    Canonical form is "first letter upper, rest lower" (:meth:`str.capitalize`),
    which collapses every casing variant measured in the real files
    (``Fruits`` / ``fruits`` / ``FRUITS``) onto one value.

    Example: ``"  FRUITS"`` / ``"fruits"`` -> ``"Fruits"``.

    Args:
        raw: The raw category string as read from a CSV cell.

    Returns:
        The stripped, canonically-cased category name.
    """
    return raw.strip().capitalize()


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
    tokens = (token.strip().lower() for token in raw.split(TAG_SEPARATOR))
    return list(dict.fromkeys(token for token in tokens if token))


def strip_text(raw: str) -> str:
    """Strip surrounding whitespace from a free-text field (N5).

    Args:
        raw: The raw text value as read from a CSV cell.

    Returns:
        ``raw`` with leading and trailing whitespace removed.
    """
    return raw.strip()


def parse_quantity(raw: str) -> Decimal:
    """Parse an inventory quantity as an exact :class:`~decimal.Decimal` (N6).

    Fractional quantities (e.g. ``"16.4"``) are preserved exactly, not
    rounded — they are plausible weight-based measurements despite the
    dataset's pieces convention (ADR-008); rounding for display happens
    only at the API layer. Non-finite decimals (``"NaN"``, ``"Infinity"``)
    are rejected by :data:`DECIMAL_PATTERN`: they are accepted by
    :class:`~decimal.Decimal` but meaningless as a quantity and unstorable
    as SQL ``NUMERIC``.

    This is also the exact-decimal parser :mod:`app.ingest.rules` uses for
    money fields (prices, profit margin), which need the same "never lose
    precision to binary floats" guarantee.

    Args:
        raw: The raw quantity string as read from a CSV cell.

    Returns:
        The parsed exact quantity.

    Raises:
        ValueError: If ``raw`` is not a valid decimal number.
    """
    text = raw.strip()
    if not DECIMAL_PATTERN.match(text):
        raise ValueError(f"quantity is not a number: {raw!r}")
    return Decimal(text)
