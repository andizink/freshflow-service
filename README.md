# FreshFlow Service

A small FastAPI service that ingests four messy grocery-retail CSV exports
(`items`, `inventory`, `orderable_items`, `order_recommendations`) and
serves, per store and ordering day, the enriched list of recommended order
quantities. The real substance of the challenge isn't the two endpoints —
it's the data underneath them: ~76,000 rows of realistic, deliberately dirty
export data (inconsistent store-ID casing, two date formats, negative
quantities, unknown item references, empty prices, exact duplicates). The
pipeline's philosophy is **normalize what is unambiguous, quarantine what
isn't, and report everything**: every upload returns a machine-readable
report of what was repaired and why, and every quarantined row stays
retrievable via the API for audit — nothing is silently dropped or silently
guessed at. See [docs/PROBLEM_ANALYSIS.md](docs/PROBLEM_ANALYSIS.md) for the
full reasoning.

## Quickstart (Docker)

```bash
docker build -t freshflow .
docker run -p 8000:8000 freshflow
```

The service is now listening on `http://localhost:8000`; interactive docs
are at `http://localhost:8000/docs`. The SQLite database defaults to
`/data/freshflow.db` *inside* the container, so it does not survive
`docker run` on its own — mount a volume to persist it across restarts:

```bash
docker run -p 8000:8000 \
  -v freshflow-data:/data \
  -e FRESHFLOW_DB_PATH=/data/freshflow.db \
  freshflow
```

Equivalently, `docker compose up --build` does the same with a named
volume preconfigured (see `docker-compose.yml`).

### Load the challenge data

With the container running, load the four real CSVs (in `data/`) and run a
sample query in one step:

```bash
BASE_URL=http://localhost:8000 ./scripts/load_all.sh
```

Or do it by hand with `curl`. Ingesting `items.csv`:

```bash
curl -sS -X POST "http://localhost:8000/api/v1/ingest/items" \
  -F "file=@data/items.csv;type=text/csv"
```

```json
{
    "ingest_id": "7eb9fe912e704c61827ccc9bd7a6be6c",
    "dataset": "items",
    "received_rows": 50,
    "loaded_rows": 50,
    "deduplicated_rows": 0,
    "quarantined_rows": 0,
    "normalizations": {
        "store_id_cleaned": 0,
        "item_number_float_coerced": 0,
        "date_format_converted": 0,
        "value_whitespace_stripped": 4,
        "casing_normalized": 3
    },
    "quarantine_summary": {},
    "warnings": []
}
```

Querying recommendations for `store_a` on `2024-01-01` (after ingesting all
four files in `items` → `inventory` → `orderable-items` →
`order-recommendations` order):

```bash
curl -sS "http://localhost:8000/api/v1/stores/store_a/recommendations?day=2024-01-01"
```

```json
{
    "store_id": "store_a",
    "day": "2024-01-01",
    "count": 48,
    "recommendations": [
        {
            "item_number": 1001,
            "item_name": "Organic Bananas",
            "category": "Fruits",
            "is_bio": false,
            "recommended_quantity": 18,
            "delivery_day": "2024-01-02",
            "current_inventory": 16,
            "purchase_price": 0.93,
            "suggested_retail_price": 1.47,
            "orderable": true,
            "tags": []
        },
        {
            "item_number": 1002,
            "item_name": "Red Apples Gala",
            "category": "Fruits",
            "is_bio": false,
            "recommended_quantity": 39,
            "delivery_day": "2024-01-02",
            "current_inventory": 27,
            "purchase_price": 1.15,
            "suggested_retail_price": 2.03,
            "orderable": true,
            "tags": []
        }
        // ... 46 more items
    ]
}
```

All example output above was captured from a real local run
(`uv run uvicorn app.main:app --port 8123`, then ingesting `data/*.csv` and
querying), not hand-written.

## API overview

Full interactive docs (request/response schemas, try-it-out) are served at
`/docs` (Swagger UI) and `/openapi.json`.

| Method & path | What it does |
|---|---|
| `POST /api/v1/ingest/{dataset}` | Upload a CSV (`items`, `inventory`, `orderable-items`, or `order-recommendations`); atomically replaces that dataset's rows and returns the ingest report. |
| `GET /api/v1/ingest/{ingest_id}` | Re-fetch a past ingest run's report by its ID. |
| `GET /api/v1/ingest/{ingest_id}/quarantine` | Paginated (`limit`/`offset`, capped at 1000) audit listing of rows quarantined by a past ingest run, with reasons. |
| `GET /api/v1/stores` | List known stores with per-dataset row counts. |
| `GET /api/v1/stores/{store_id}/recommendations?day=YYYY-MM-DD` | Enriched order recommendations for a store and ordering day (name, category, price, current inventory, orderable flag). |
| `GET /health` | Liveness probe used by the Docker `HEALTHCHECK`. |

## Local development

```bash
uv sync --all-groups
```

Verification matrix (also what CI runs, `.github/workflows/ci.yml`):

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -m "not e2e and not smoke" --cov=app --cov-branch --cov-fail-under=90
uv run pytest -m e2e
uv run pytest -m smoke   # requires a working Docker daemon; builds and runs the real image
```

## Testing

416 tests total, organized as a pyramid:

| Layer | Count | What it covers |
|---|---|---|
| Unit (`tests/unit/`) | 366 | Pure functions — normalization rules N1–N7, quarantine rules Q1–Q5, dedup key, CSV header parsing — table-driven, no DB/HTTP — plus the traceability and docs meta-tests. |
| Integration (`tests/integration/`) | 43 | 29 exercise the ingest endpoint end-to-end against an isolated test DB (atomic replace, reports, quarantine pagination bounds, encoding rejection); 13 exercise the recommendations/stores/health endpoints (joins, 404s, enrichment); 1 pins the committed OpenAPI snapshot. |
| E2E (`tests/e2e/`) | 6 | The real `data/*.csv` files ingested in order and checked against pinned counts (`tests/e2e/expected_counts.json`, generated independently by `scripts/generate_expected_counts.py`, a standalone re-derivation of the N1–N7/Q1–Q5 rules with no import of `app/`). |
| Smoke (`tests/e2e/test_container_smoke.py`) | 1 (skipped locally) | Builds the production Docker image, runs it, ingests + queries through the real container, inspects it for the non-root user and healthcheck. Skips with `pytest.skip` when no Docker daemon is reachable (always true in this sandbox); runs for real in CI's `docker` job. |

Measured branch coverage: **97%** (`--cov-branch`, CI gate is `--cov-fail-under=90`).

## Design

The four files carry realistic export defects — measured by profiling the
real data and independently re-verified by `scripts/generate_expected_counts.py`
against `tests/e2e/expected_counts.json` (the authoritative source for every
count below). Headline numbers from that file:

| Dataset | Received | Loaded | Deduplicated | Quarantined |
|---|---:|---:|---:|---:|
| `items` | 50 | 50 | 0 | 0 |
| `inventory` | 25,868 | 25,120 | 118 | 630 (`unknown_item`) |
| `orderable-items` | 25,200 | 23,139 | 186 | 1,875 (1,299 `missing_field` + 610 `unknown_item`) |
| `order-recommendations` | 25,627 | 23,900 | 286 | 1,441 (515 `negative_quantity` + 941 `unknown_item`) |

The guiding rule, applied case by case: **repair only what has exactly one
reasonable interpretation (safe normalization); set aside anything else
with a reason code (quarantine); never lose data silently.** For example, a
store ID spelled `" STORE_A "` is unambiguously `store_a` (normalized); a
recommendation to order `-5` pieces has no defensible correct value
(quarantined, reason `negative_quantity`); an `orderable_items` row with no
`purchase_price` can't be priced and is quarantined as `missing_field`
rather than defaulting to a made-up `0.00`.

Full detail:

- [docs/PROBLEM_ANALYSIS.md](docs/PROBLEM_ANALYSIS.md) — the business
  problem and the design tensions any solution has to resolve.
- [docs/DATA_GUIDE.md](docs/DATA_GUIDE.md) — plain-language walkthrough of
  every defect (D1–D10) and what the pipeline does about it, for developers
  new to the domain.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — runtime architecture,
  package layering, data model, and the ingest/query sequence diagrams.
- [docs/DATA_QUALITY.md](docs/DATA_QUALITY.md) — the formal defect → rule →
  implementation → test traceability matrix.
- [docs/adr/](docs/adr/) — 16 architecture decision records covering every
  non-obvious design choice (storage, error format, decimal handling,
  ingest report semantics, upload size enforcement, and more).
