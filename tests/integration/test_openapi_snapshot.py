"""Meta-test: the OpenAPI schema must match the committed snapshot.

PLAN.md §6.1 mandates a committed ``openapi.json`` snapshot so that any
change to the API contract — a renamed field, a changed status code, a new
endpoint — surfaces as an explicit test failure instead of a silent drift.

To update the snapshot after an *intentional* contract change, run::

    uv run python -m scripts.dump_openapi

and commit the regenerated ``tests/snapshots/openapi.json`` together with
the code change (and, if user-visible, an ADR or changelog note).
"""

import json
from pathlib import Path

from app.main import create_app

SNAPSHOT_PATH = Path(__file__).parent.parent / "snapshots" / "openapi.json"


def _canonical(schema: object) -> str:
    """Serialize a schema deterministically for comparison."""
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def test_openapi_schema_matches_committed_snapshot() -> None:
    """The live schema and the committed snapshot must be byte-identical."""
    live = _canonical(create_app().openapi())
    committed = SNAPSHOT_PATH.read_text(encoding="utf-8")

    assert live == committed, (
        "OpenAPI schema drifted from tests/snapshots/openapi.json. If the "
        "contract change is intentional, regenerate the snapshot with "
        "`uv run python -m scripts.dump_openapi` and commit it."
    )
