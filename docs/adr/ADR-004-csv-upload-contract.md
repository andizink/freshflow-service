# ADR-004: CSV upload contract

Status: Accepted
Date: 2026-08-16

## Context

The service must accept four distinct CSV files (`items`, `inventory`,
`orderable_items`, `order_recommendations`), each with its own header
schema and its own set of normalization/quarantine rules. The upload
mechanism needs to make it unambiguous which dataset a given file
represents (so the correct header validation and rule set apply), needs to
support re-uploading a corrected file (ADR-009's replace semantics), and
needs to produce a clear error when a file's header doesn't match what its
declared dataset expects.

## Options Considered

- **`POST /api/v1/ingest/{dataset}` with a multipart file field (chosen)**
  — The caller states which dataset they intend to load in the URL path;
  the server validates the uploaded file's header against that dataset's
  expected columns and returns a dataset-specific ingest report. This is
  explicit and self-documenting (the URL alone tells you what happened),
  gives one report per file (rather than one combined, harder-to-read
  report for four files at once), and is naturally idempotent per dataset
  — re-uploading `inventory.csv` only replaces the inventory table. The
  downside is that loading all four files requires four separate HTTP
  calls instead of one; this is a minor ergonomics cost, mitigated by
  providing a `scripts/load_all.sh` convenience script that issues all
  four calls.
- **Single endpoint with filename-based dataset sniffing** — One endpoint,
  one call per file, dataset inferred from the filename (e.g.
  `inventory.csv` → inventory dataset). This saves the caller from stating
  the dataset explicitly, but it is magic: the behavior silently changes if
  a file is renamed, and it couples the API contract to filenames, which
  are not a reliable, versioned part of any real client's contract with the
  server. Header-shape sniffing (guessing the dataset from which columns
  are present) is no better — several of the datasets share column names
  (`store_id`, `item_number`, `ordering_day`), so a wrong guess is a real
  risk with a bad failure mode (data loaded into the wrong table).
- **Server-side path loading** (client tells the server a filesystem path
  to read) — Trivial to implement, but this is barely an API: it assumes
  the CSV files already exist somewhere the server process can read, which
  couples the client and server filesystems and does not model a real
  "upload data over HTTP" integration at all. It also creates an
  unnecessary local file-read attack surface.

## Decision

Use **`POST /api/v1/ingest/{dataset}`** where `dataset` is a path parameter
constrained to a `StrEnum` (`items`, `inventory`, `orderable-items`,
`order-recommendations`) and the file arrives as a `multipart/form-data`
field named `file`. Each call replaces that one dataset's rows atomically
(ADR-009) and returns that dataset's `IngestReport`. A convenience script,
`scripts/load_all.sh`, issues all four calls in sequence for demo purposes;
no combined single-call endpoint is provided, keeping one dataset's report
unambiguous and self-contained.

Ingesting a per-store dataset (`inventory`, `orderable-items`,
`order-recommendations`) before `items` is explicitly **allowed**, not
rejected with `409`: the unknown-item quarantine count (Q2) will simply
reflect whatever catalog is currently loaded (possibly empty), and the
report carries a warning recommending an items-first ingest order. There is
no hard ordering dependency enforced by the API.

## Consequences

**Positive:**

- The dataset a given upload targets is always explicit and machine-checked
  (an invalid `dataset` path segment is rejected before any file parsing
  happens), eliminating an entire class of "loaded into the wrong table"
  bugs.
- Per-dataset reports are easy to reason about and test independently —
  the e2e suite can assert exact counts for each of the four real files
  without needing to disentangle a combined report.
- Re-ingesting one corrected file is a single, obviously-scoped call; it
  does not require re-uploading the other three datasets.

**Negative:**

- Loading the full dataset requires four HTTP calls instead of one; the
  `scripts/load_all.sh` script exists specifically to paper over this for
  demos and local testing, but a genuinely single-call bulk-load path is
  not part of the API contract.
- Because items-first ordering is not enforced, a caller who ingests the
  per-store files before `items` will see inflated `unknown_item`
  quarantine counts that are really just "catalog not loaded yet," not a
  genuine data defect — this must be read from the warning message, not
  assumed from the number alone.
