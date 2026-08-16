#!/usr/bin/env bash
# Demo/smoke-load script: POSTs the four real challenge CSVs to a running
# FreshFlow instance, in the order the ingest contract requires (items
# first, so the per-store files' unknown_item check runs against a fully
# loaded catalog - PLAN.md §3.1), printing each ingest report, then runs one
# sample recommendations query.
#
# Usage:
#   BASE_URL=http://localhost:8000 ./scripts/load_all.sh
#
# BASE_URL defaults to http://localhost:8000 if unset.

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
repo_root="$(cd -- "${script_dir}/.." >/dev/null 2>&1 && pwd)"
data_dir="${repo_root}/data"

ingest() {
  local dataset="$1"
  local file_path="$2"

  echo "==> ingesting ${dataset} (${file_path})"
  curl -fsS -X POST \
    "${BASE_URL}/api/v1/ingest/${dataset}" \
    -F "file=@${file_path};type=text/csv" \
    | python3 -m json.tool
  echo
}

ingest "items" "${data_dir}/items.csv"
ingest "inventory" "${data_dir}/inventory.csv"
ingest "orderable-items" "${data_dir}/orderable_items.csv"
ingest "order-recommendations" "${data_dir}/order_recommendations.csv"

echo "==> sample query: store_a recommendations for 2024-01-01"
curl -fsS \
  "${BASE_URL}/api/v1/stores/store_a/recommendations?day=2024-01-01" \
  | python3 -m json.tool
