#!/usr/bin/env bash
# Reproduce every headline claim in README.md and print PASS/FAIL per claim.
#
# Purpose: a reviewer should not have to trust this repository's prose.
# This script turns each documented number into a live check:
#
#   C1  ruff check is clean
#   C2  ruff format --check is clean
#   C3  mypy --strict is clean
#   C4  exactly 416 tests are collected
#   C5  unit+integration suite passes with branch coverage >= 90%
#   C6  e2e suite passes (ingest reports for the real CSVs match the
#       pinned tests/e2e/expected_counts.json, field for field)
#   C7  the pinned counts are independently re-derivable: the stdlib-only
#       scripts/generate_expected_counts.py (no app/ imports) regenerates
#       a byte-identical fixture
#   C8  the README's sample query response is real: store_a / 2024-01-01
#       returns 48 recommendations; item 1001 -> quantity 18, delivery
#       2024-01-02, current_inventory 16, prices 0.93 / 1.47
#
# Requirements: `uv sync --all-groups` has been run. No Docker needed.
# Exit code: 0 iff every claim passes.

set -u
cd "$(dirname "$0")/.."

PASS=0
FAIL=0
declare -a RESULTS=()

check() {
  local name="$1"
  shift
  if "$@" >/tmp/verify_claim_out.log 2>&1; then
    RESULTS+=("PASS  $name")
    PASS=$((PASS + 1))
  else
    RESULTS+=("FAIL  $name  (see output below)")
    FAIL=$((FAIL + 1))
    echo "--- output of failed check: $name ---"
    tail -40 /tmp/verify_claim_out.log
    echo "---"
  fi
}

c4_test_count() {
  local count
  count=$(uv run pytest --collect-only -q 2>/dev/null | tail -1 | grep -oE '^[0-9]+')
  [ "$count" = "416" ] || { echo "collected $count tests, README claims 416"; return 1; }
}

c7_regenerate_counts() {
  local tmp
  tmp=$(mktemp -d)
  cp tests/e2e/expected_counts.json "$tmp/pinned.json"
  uv run python scripts/generate_expected_counts.py >/dev/null || return 1
  if ! diff -q "$tmp/pinned.json" tests/e2e/expected_counts.json >/dev/null; then
    echo "regenerated counts differ from the committed pin"
    diff "$tmp/pinned.json" tests/e2e/expected_counts.json | head -20
    cp "$tmp/pinned.json" tests/e2e/expected_counts.json  # restore
    return 1
  fi
}

c8_sample_response() {
  uv run python - << 'PY'
import sys
import tempfile
from pathlib import Path

# Run against a throwaway DB so this check never touches a local dev DB.
import os
tmpdir = tempfile.mkdtemp()
os.environ["FRESHFLOW_DB_PATH"] = str(Path(tmpdir) / "verify.db")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import create_app  # noqa: E402

app = create_app()
with TestClient(app) as client:
    for dataset, filename in (
        ("items", "items.csv"),
        ("inventory", "inventory.csv"),
        ("orderable-items", "orderable_items.csv"),
        ("order-recommendations", "order_recommendations.csv"),
    ):
        path = Path("data") / filename
        with path.open("rb") as fh:
            r = client.post(
                f"/api/v1/ingest/{dataset}",
                files={"file": (filename, fh, "text/csv")},
            )
        assert r.status_code == 200, f"{dataset}: HTTP {r.status_code}"

    r = client.get("/api/v1/stores/store_a/recommendations?day=2024-01-01")
    assert r.status_code == 200, f"query: HTTP {r.status_code}"
    body = r.json()
    assert body["count"] == 48, f"count {body['count']} != 48"
    item = {x["item_number"]: x for x in body["recommendations"]}[1001]
    expected = {
        "item_name": "Organic Bananas",
        "recommended_quantity": 18,
        "delivery_day": "2024-01-02",
        "current_inventory": 16,
        "purchase_price": 0.93,
        "suggested_retail_price": 1.47,
        "orderable": True,
    }
    for key, want in expected.items():
        got = item[key]
        assert got == want, f"item 1001 {key}: {got!r} != {want!r}"
print("sample response matches README")
PY
}

echo "FreshFlow claim verification"
echo "============================"

check "C1 ruff check clean"                    uv run ruff check .
check "C2 ruff format --check clean"           uv run ruff format --check .
check "C3 mypy --strict clean"                 uv run mypy
check "C4 exactly 416 tests collected"         c4_test_count
check "C5 unit+integration pass, branch coverage >= 90%" \
  uv run pytest -m "not e2e and not smoke" --cov=app --cov-branch --cov-fail-under=90 -q
check "C6 e2e: real-CSV ingest reports match pinned counts" \
  uv run pytest -m e2e -q
check "C7 pinned counts re-derived independently (byte-identical)" \
  c7_regenerate_counts
check "C8 README sample response reproduces (store_a 2024-01-01)" \
  c8_sample_response

echo
echo "Results"
echo "-------"
for line in "${RESULTS[@]}"; do echo "$line"; done
echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
