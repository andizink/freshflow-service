# FreshFlow — Test Plan (integration & end-to-end)

*This document explains, in plain language, what the integration and
end-to-end test suites check and why each check exists. It is written for
someone who has never seen the codebase: each case says what situation we
set up, what we do, and what must happen. The fine-grained unit tests
(366 of them, one module per data rule) are not listed case-by-case here —
they are catalogued by rule ID in [DATA_QUALITY.md](DATA_QUALITY.md); this
plan covers everything above that layer.*

---

## 1. The test pyramid at a glance

| Layer | Where | Count | Question it answers |
|---|---|---|---|
| Unit | `tests/unit/` | 366 | "Does each cleaning/quarantine rule do exactly what its spec says, for every nasty input we found?" |
| Integration | `tests/integration/` | 43 | "Do the HTTP endpoints, the database, and the rules work correctly *together*, on small handcrafted files?" |
| End-to-end | `tests/e2e/test_real_data.py` | 6 | "Does the whole service produce exactly the right numbers on the *real* challenge files?" |
| Container smoke | `tests/e2e/test_container_smoke.py` | 1 | "Does the actual Docker image build, start, and serve correctly?" |

How to run them:

```bash
uv run pytest -m "not e2e and not smoke"   # unit + integration (fast, ~5 s)
uv run pytest -m e2e                        # real-data suite (~20 s)
uv run pytest -m smoke                      # needs a Docker daemon; skips otherwise
```

**Test data.** Integration tests never touch the real CSVs. They use tiny
handcrafted files in `tests/fixtures/` — one per defect class (a file with
store-id variants, a file with a negative quantity, a file with a bad
header, and so on) — so each test controls exactly what goes in and can
assert exactly what must come out. Every test also gets its own fresh,
empty SQLite database, so tests can never influence each other.

---

## 2. Integration tests — ingest pipeline (`test_ingest.py`)

### 2.1 The happy path

**Clean file loads untouched.** Upload a well-formed items catalog. Every
row must load; the report must show zero repairs, zero duplicates, zero
quarantined rows. This is the baseline: if this fails, nothing else in the
suite means anything.

### 2.2 One test per data defect

Each of these uploads a small file containing one specific defect and
asserts the exact ingest report — not just "it worked", but the precise
counts and reason codes the report must show.

| Case | Given a file that contains… | The service must… |
|---|---|---|
| Store-id variants (N1) | `STORE_A`, `" store_a"`, `"store_a "` | Load all rows under the clean id `store_a` and count each repair as `store_id_cleaned`. |
| Float item numbers (N2) | `"1001.0"` and `"1001.5"` | Coerce `1001.0` → `1001` (counted); quarantine `1001.5` — half an item number means the value is corrupt, and guessing could attach data to the wrong product. |
| Unknown item (Q2) | an item number not in the loaded catalog | Quarantine the row with reason `unknown_item` — without a catalog entry we know neither name nor price. |
| Unknown items, empty catalog | per-store data uploaded before any catalog | Quarantine everything as `unknown_item` *and* add a warning recommending items-first upload order. |
| Negative quantity (Q1) | `recommended_quantity = -5` | Quarantine with reason `negative_quantity` — "order −5 pieces" is not an actionable instruction. |
| Delivery before ordering (Q5) | a delivery day earlier than the ordering day | Quarantine with reason `invalid_date_order` — goods cannot arrive before they were ordered. |
| Exact duplicates (N7) | the same row twice, byte-identical values | Load it once, count one `deduplicated_row`, quarantine nothing — dropping an identical copy loses no information. |
| Conflicting duplicates (Q4) | the same key twice with *different* values | Load the first occurrence, archive **both** raw versions in quarantine as `conflicting_duplicate`, and raise a warning — we genuinely don't know which is true, so we keep the audit trail. |
| Mixed date formats (N3) | `23/01/2024` next to ISO dates, plus one unparseable date | Convert the day-first slash date (counted as `date_format_converted`); quarantine the unparseable one — a *wrong* date is worse than a missing row. |
| Fractional inventory (N6) | a quantity of `16.4` pieces | Load the exact value (never round away information at ingest) and emit one warning line with the fractional-row count. |
| Complete cross-file data | recommendations where every row has a matching order window | Raise **no** "missing window" warning — the warning must only fire when a gap really exists. |

### 2.3 Report retrieval & quarantine audit

**A report can be re-fetched later.** `GET /api/v1/ingest/{id}` must return
the exact same JSON the original upload returned — reports are stored, not
ephemeral.

**Unknown ingest ids fail cleanly.** Both the report and the quarantine
endpoints must answer a made-up id with `404` and a proper
`application/problem+json` body, never a stack trace.

**Quarantine preserves the evidence.** The audit endpoint must return each
quarantined row's *raw, unmodified* input values together with its reason
codes — an auditor must be able to see exactly what was rejected and why.

**Pagination behaves.** `limit`/`offset` slice the quarantine list while
`total` always reports the full count; a limit above 1000 is capped at
1000; and a negative or zero limit — which would otherwise disable
SQLite's row cap entirely and dump the whole table — is rejected with
`422` (three parametrized cases: `limit=-5`, `limit=0`, `offset=-3`).

### 2.4 Upload error handling

Every one of these must fail *cleanly*: correct status code, a
problem+json body a human can act on, and — crucially — no change
whatsoever to previously loaded data.

| Case | Upload | Expected answer |
|---|---|---|
| Wrong header | a CSV whose columns don't match the dataset | `400`, with the expected and found column lists spelled out in the message. |
| Empty file | zero bytes | `400` — an empty file has no header to validate. |
| Wrong dataset name | POST to `/ingest/nonsense` | `422` — the dataset path segment is validated against the four known names. |
| Oversized file | a body larger than the configured limit | `413`, detected while streaming (the service never trusts the Content-Length header), and nothing is loaded. |
| Non-UTF-8 bytes | a binary/garbage file behind a valid header | `400` "Invalid CSV encoding", and a previously loaded dataset is untouched — verified by counting rows before and after. |

### 2.5 Replace semantics & atomicity

These three tests pin the ingest contract that makes re-uploads safe:

**Idempotency.** Uploading the same file twice yields the same report and
the same table row count — no accumulation, no drift.

**Atomicity.** A good upload followed by a *failed* upload (bad header)
leaves the good data byte-for-byte intact — an ingest either fully
happens or fully doesn't.

**Replace, not merge.** Re-uploading a dataset with fewer rows leaves
exactly those fewer rows in the table — the upload *replaces* the
dataset, it never merges into it.

---

## 3. Integration tests — query endpoints

### 3.1 Recommendations (`test_query_recommendations.py`)

The recommendations endpoint joins four tables; each test seeds the
database directly with a controlled combination and checks the response
field by field.

| Case | Situation | The response must… |
|---|---|---|
| Full enrichment | catalog + inventory + window all present | Contain every field correctly: item name/category/bio flag from the catalog, the window's prices (overriding the catalog's), `orderable: true`, tags, delivery day, rounded inventory. |
| Dirty store id in URL | `GET /stores/%20STORE_A%20/recommendations` | Resolve to `store_a` and answer identically to the clean spelling — the same cleaning rule (N1) applies to input as to data. |
| Unknown store | a store id that appears in no table | `404` with a problem+json body (not an empty list — an unknown store is an error, an empty day is not). |
| Malformed day | `day=2024-13-45` | `422` from date validation. |
| Missing day | no `day` parameter at all | `422` — the parameter is required. |
| Known store, quiet day | store exists, no recommendations that day | `200` with `count: 0` and an empty list — a valid question with an empty answer is not an error. |
| No order window | recommendation without a matching window | `orderable: false`, catalog prices as fallback, empty tags — the recommendation is shown with a caveat, never hidden. |
| No inventory row | no same-day stock record | `current_inventory: null` — absence of knowledge is not zero. |
| Fractional stock | inventory of 16.4 and 16.5 | `16` and `17` — half-up rounding for display, while the exact value stays in the database. |
| Item not in catalog | deliberately unseeded item | `null` item fields rather than a crash — defensive behavior for a state quarantine normally prevents. |

### 3.2 Stores, health, and the API contract

**Store listing.** `GET /stores` aggregates per-store row counts across all
three per-store tables and returns them sorted; with an empty database it
returns an empty list.

**Health.** `GET /health` answers `200 {"status": "ok"}` — the check the
Docker HEALTHCHECK and any orchestrator relies on.

**OpenAPI snapshot.** The live OpenAPI schema must be byte-identical to
the committed `tests/snapshots/openapi.json`. Any change to the API
contract — a renamed field, a changed status code — fails this test, so a
contract change is always an explicit, reviewed decision, never an
accident.

---

## 4. End-to-end tests — the real challenge data (`test_real_data.py`)

This suite answers the question the whole project hangs on: *given the
four real CSV files, does the service produce exactly the right result?*
"Exactly" is not rhetorical — the expected numbers live in
`tests/e2e/expected_counts.json`, which is generated by
`scripts/generate_expected_counts.py`, a standalone script that
re-implements the cleaning rules from the documentation **without
importing any service code**. The service and the script derive the
numbers independently; the test asserts they agree.

**Fixture sanity.** The expected-counts file must contain an entry for all
four datasets — guards against a silently truncated regeneration.

**Full ingest, exact reports.** All four files are uploaded in order
(catalog first). Every report field must match the independent derivation:
received/loaded/deduplicated/quarantined counts, every normalization
counter, every quarantine reason count. Headline numbers: inventory
25,868 → 25,120 loaded; orderable windows 25,200 → 23,139; recommendations
25,627 → 23,900, with 515 negative quantities and 941 unknown items
quarantined.

**Known-row spot check.** For store_a / item 1001 / 2024-01-01 the
response must say: order 18 Organic Bananas, arriving 2024-01-02, current
inventory 16 (rounded from 16.4), orderable, with the window's prices —
every value traced back to the raw CSVs by hand.

**Store listing on real data.** Exactly `store_a` and `store_b`, with
row counts matching the loaded totals.

**Quarantine audit on real data.** The recommendations ingest's quarantine
page must actually surface rows with reason `negative_quantity`.

**Idempotency at full scale.** Re-ingesting the full recommendations file
gives a byte-identical report (ids aside) — replace semantics hold at
25k-row scale, not just on toy fixtures.

---

## 5. Container smoke test (`test_container_smoke.py`)

One test that treats the Docker image — not the Python code — as the unit
under test. It builds the image, starts a container on a free port with a
fresh volume, waits for `/health`, pushes all four real CSVs through the
running container, checks the reports against the same pinned counts,
queries recommendations, and inspects the image for the non-root user and
the HEALTHCHECK. The container is always torn down, even on failure.

When no Docker daemon is reachable (as in the build sandbox), the test
skips with an explicit reason instead of failing; CI's `docker` job runs
it for real after `hadolint` and `docker build`.

---

## 6. What keeps this plan honest

Three meta-tests watch the watchers: the **traceability test** pins which
functions implement which rule IDs (so this document, the code, and the
tests can't silently drift apart), the **docs test** checks the ADRs and
diagrams keep their required structure, and the **OpenAPI snapshot**
freezes the API contract. Coverage is enforced at ≥90% line *and* branch
(currently ~97%) in CI, and the full verification matrix — lint, types,
tests, coverage, container — is documented in the README's development
section.
