"""Shared enumerations: dataset kinds and quarantine reason codes.

These enums are the vocabulary shared by the parser, normalization/rules
modules, ORM models, and API schemas (PLAN.md §3, §4.2, §4.3). Keeping them
in one dependency-free module avoids import cycles between ``app.ingest``
and ``app.schemas``.
"""

from enum import StrEnum


class DatasetKind(StrEnum):
    """The four ingestible dataset kinds, keyed by their API path segment.

    See PLAN.md §3.1 for the ``POST /api/v1/ingest/{dataset}`` contract.
    """

    ITEMS = "items"
    INVENTORY = "inventory"
    ORDERABLE_ITEMS = "orderable-items"
    ORDER_RECOMMENDATIONS = "order-recommendations"


class ReasonCode(StrEnum):
    """Quarantine reason codes, one per row-rejection rule Q1-Q5 (PLAN.md §4.3).

    Attributes:
        NEGATIVE_QUANTITY: Q1 - ``recommended_quantity < 0``.
        UNKNOWN_ITEM: Q2 - ``item_number`` not present in the items catalog
            at ingest time.
        INVALID_VALUE: Q3 - a field value could not be parsed.
        MISSING_FIELD: Q3 - a required field was empty or absent.
        CONFLICTING_DUPLICATE: Q4 - duplicate key with differing payloads.
        INVALID_DATE_ORDER: Q5 - ``delivery_day < ordering_day``.
    """

    NEGATIVE_QUANTITY = "negative_quantity"
    UNKNOWN_ITEM = "unknown_item"
    INVALID_VALUE = "invalid_value"
    MISSING_FIELD = "missing_field"
    CONFLICTING_DUPLICATE = "conflicting_duplicate"
    INVALID_DATE_ORDER = "invalid_date_order"
