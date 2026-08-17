# ADR-004: CSV upload contract

Status: Accepted
Date: 2026-08-16

## Context

The service must accept four distinct CSV files (`items`, `inventory`,
`orderable_items`, `order_recommendations`), each with its own header
schema and its own set of normalization and quarantine rules. The upload
mechanism needs to make it unambiguous which dataset a given file
represents, so the correct header validation and rule set apply. It also
needs to support re-uploading a corrected file (ADR-009's replace
semantics) and to produce a clear error when a file's header doesn't match
its declared dataset.

## Options Considered

- **`POST /api/v1/ingest/{dataset}` with a multipart file field (chosen)**
  — The caller states which dataset they intend to load in the URL path,
  and the server validates the uploaded file's header against that
  dataset's expected columns before returning a dataset-specific ingest
  report. This is explicit and self-documenting: the URL alone tells you
  what happened. It gives one report per file rather than one combined,
  harder-to-read report for four files at once, and it is naturally
  idempotent per dataset, since re-uploading `inventory.csv` only replaces
  the inventory table. The downside is four HTTP calls to load everything
  instead of one, a minor ergonomics cost mitigated by the
  `scripts/load_all.sh` convenience script.
- **Single endpoint with filename-based dataset sniffing** — Dataset
  inferred from the filename (`inventory.csv` → inventory dataset). Saves
  the caller from stating the dataset, but it is magic: behavior changes
  silently if a file is renamed, and it couples the API contract to
  filenames, which are not a reliable, versioned part of any real client's
  contract. Header-shape sniffing is no better, since several datasets
  share column names (`store_id`, `item_number`, `ordering_day`) and a
  wrong guess loads data into the wrong table.
- **Server-side path loading**, where the client tells the server a
  filesystem path to read. Trivial to implement, but barely an API: it
  assumes the CSVs already exist where the server process can read them,
  couples the client and server filesystems, and adds a local file-read
  attack surface for nothing.

## Decision

Use **`POST /api/v1/ingest/{dataset}`** where `dataset` is a path parameter
constrained to a `StrEnum` (`items`, `inventory`, `orderable-items`,
`order-recommendations`) and the file arrives as a `multipart/form-data`
field named `file`. Each call replaces that one dataset's rows atomically
(ADR-009) and returns that dataset's `IngestReport`. A convenience script,
`scripts/load_all.sh`, issues all four calls in sequence for demo purposes.
No combined single-call endpoint is provided, which keeps each dataset's
report unambiguous and self-contained.

Ingesting a per-store dataset (`inventory`, `orderable-items`,
`order-recommendations`) before `items` is explicitly **allowed**, not
rejected with `409`. The unknown-item quarantine count (Q2) simply reflects
whatever catalog is currently loaded, possibly empty, and the report
carries a warning recommending an items-first ingest order. The API
enforces no hard ordering dependency.

## Consequences

The dataset a given upload targets is always explicit and machine-checked —
an invalid `dataset` path segment is rejected before any file parsing
happens — which eliminates a whole class of "loaded into the wrong table"
bugs. Per-dataset reports are also easy to test independently: the e2e
suite asserts exact counts for each of the four real files without
disentangling a combined report. Re-ingesting one corrected file is a
single, obviously-scoped call.

Two things to be aware of:

- Loading the full dataset takes four HTTP calls. `scripts/load_all.sh`
  papers over this for demos and local testing, but a genuine single-call
  bulk-load path is not part of the API contract.
- Because items-first ordering is not enforced, a caller who ingests the
  per-store files first sees inflated `unknown_item` quarantine counts that
  really mean "catalog not loaded yet." That has to be read from the
  warning message, not assumed from the number alone.
