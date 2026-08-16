# ADR-005: Processing pipeline

Status: Accepted
Date: 2026-08-16

## Context

Ingest needs to read CSV files (up to ~26,000 rows each), apply per-row
normalization and validation, and produce precise per-row diagnostics (which
row number, which reason) for the quarantine audit trail. The processing
approach affects memory footprint, container image size, and how precisely
errors can be attributed to a source row.

## Options Considered

- **stdlib `csv` module, streaming, row-by-row (chosen)** — `csv.DictReader`
  reads one row at a time; each row is passed through a Pydantic-backed
  normalization/validation step
  (`app/ingest/normalize.py`, `app/ingest/rules.py`) before being
  accumulated for a single bulk insert per dataset. Memory stays flat
  regardless of file size (relevant even though today's files are modest —
  ~26k rows — because the design should not silently break on a larger
  upload), and every row can be attributed to its exact 1-indexed source
  line number in the ingest report and in `quarantine_rows.row_number`.
  This adds zero new runtime dependencies beyond what's already needed
  (the stdlib `csv` module ships with Python).
- **pandas** — Would make some transformations (bulk date parsing, groupby
  dedup) more concise, and is a natural fit for analytics-style batch
  processing. But it pulls in a large dependency (tens of megabytes,
  inflating both the Docker image and the dependency-audit surface) purely
  to do row-wise validation that a streaming loop already does simply. It
  is also awkward for precise, per-row error attribution: DataFrame
  vectorized operations naturally lose the "which exact row and why" trail
  the quarantine audit design depends on, requiring extra bookkeeping to
  claw back what streaming gives for free.
- **Bulk-load then validate in SQL** (`COPY`/`.import`-style load followed
  by SQL constraint checks) — Fast for well-formed data, but this dataset's
  defects are exactly the kind SQL constraints handle badly: a `CHECK`
  constraint can reject a negative quantity but cannot *repair* `"1001.0"`
  into `1001`, and a failed bulk load in SQLite typically aborts the whole
  statement rather than yielding row-level diagnostics. This approach fits
  "reject broken data," not "normalize what's fixable," which is not the
  policy this service implements (ADR-003).

## Decision

Use the stdlib `csv` module in streaming mode
(`app.ingest.parser.read_rows`), yielding `(row_number, raw_row)` pairs that
flow through `app.ingest.rules.process_row` one at a time. Accepted rows are
accumulated and inserted in a single bulk operation per dataset inside one
transaction (ADR-009); pandas is deliberately not a dependency of this
service.

## Consequences

**Positive:**

- Memory usage is flat and predictable regardless of input file size —
  the pipeline never holds the whole raw file in memory at once (only the
  accumulated accepted rows, which is unavoidable given the atomic-replace
  transaction boundary).
- Every quarantined row carries its exact source row number, satisfying the
  audit requirement (ADR-010) precisely.
- No pandas dependency: smaller Docker image, smaller dependency-security
  surface, and one less library whose type stubs and API surface `mypy
  --strict` would otherwise have to reconcile with the rest of the typed
  codebase.

**Negative:**

- Row-by-row Python-level processing is slower than pandas' vectorized
  operations for equivalent transformations; at the current data volume
  (tens of thousands of rows) this is not observable, but it would not be
  the right architecture for a dataset many orders of magnitude larger.
- Bulk analytics-style operations (e.g. "what's the distribution of
  fractional quantities") that pandas would make a one-liner have to be
  done separately (the standalone profiling script referenced by
  `tests/e2e/expected_counts.json`, not the ingest pipeline itself) rather
  than reusing ingest-path code.
