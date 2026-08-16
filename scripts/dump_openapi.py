"""Regenerate the committed OpenAPI snapshot (tests/snapshots/openapi.json).

Run after an intentional API contract change::

    uv run python -m scripts.dump_openapi

The snapshot is asserted byte-identical to the live schema by
``tests/integration/test_openapi_snapshot.py`` (PLAN.md §6.1: contract
drift is an explicit test failure, never a surprise).
"""

import json
from pathlib import Path

from app.main import create_app

SNAPSHOT_PATH = Path(__file__).parent.parent / "tests" / "snapshots" / "openapi.json"


def main() -> None:
    """Write the current OpenAPI schema to the snapshot path."""
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = create_app().openapi()
    SNAPSHOT_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {SNAPSHOT_PATH}")


if __name__ == "__main__":
    main()
