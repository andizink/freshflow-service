# ADR-005: Processing pipeline

Status: Accepted
Date: 2026-08-16

## Context

Ingest needs to read CSV files (up to ~26,000 rows each), apply per-row
normalization and validation, and produce precise per-row diagnostics —
which row number, which reason — for the quarantine audit trail. The
processing approach drives memory footprint, container image size, and how
precisely an error can be attributed to a source row.

## Options Considered

- **stdlib `csv` module, streaming, row-by-row (chosen)** —
  `csv.DictReader` reads one row at a time. Each row passes through a
  Pydantic-backed normalization/validation step (`app/ingest/normalize.py`,
  `app/ingest/rules.py`) before being accumulated for a single bulk insert
  per dataset. Memory stays flat regardless of file size, which matters
  even though today's files are modest at ~26k rows, because the design
  should not silently break on a larger upload. Every row can be attributed to its
  exact 1-indexed source line number in the ingest report and in
  `quarantine_rows.row_number`. No new runtime dependency: the `csv` module
  ships with Python.
- **pandas** — Would make bulk date parsing and groupby dedup more concise,
  and it is a natural fit for analytics-style batch processing. But it
  pulls in tens of megabytes of dependency, inflating both the Docker image
  and the dependency-audit surface, purely to do row-wise validation a
  streaming loop already does simply. It is also awkward for per-row error
  attribution: vectorized DataFrame operations lose the "which exact row
  and why" trail the quarantine design depends on, so you end up doing
  extra bookkeeping to claw back what streaming gives for free.
- **Bulk-load then validate in SQL** (`COPY`/`.import`-style load followed
  by SQL constraint checks) — Fast for well-formed data, but this dataset's
  defects are the kind SQL constraints handle badly. A `CHECK` constraint
  can reject a negative quantity; it cannot *repair* `"1001.0"` into
  `1001`. A failed bulk load in SQLite typically aborts the whole statement
  rather than yielding row-level diagnostics. This fits "reject broken
  data," not "normalize what's fixable," which is not the policy this
  service implements (ADR-003).

## Decision

Use the stdlib `csv` module in streaming mode
(`app.ingest.parser.read_rows`), yielding `(row_number, raw_row)` pairs that
flow through `app.ingest.rules.process_row` one at a time. Accepted rows are
accumulated and inserted in a single bulk operation per dataset inside one
transaction (ADR-009). pandas is deliberately not a dependency of this
service.

## Consequences

Memory usage is flat and predictable whatever the input file size — the
pipeline never holds the whole raw file at once, only the accumulated
accepted rows, which the atomic-replace transaction boundary makes
unavoidable. Every quarantined row carries its exact source row number,
which is what the audit requirement (ADR-010) needs. Skipping pandas also
means a smaller image, a smaller dependency-security surface, and one less
library whose type stubs `mypy --strict` would have to reconcile with the
rest of the codebase.

Against that:

- Row-by-row Python processing is slower than pandas' vectorized
  equivalents. At tens of thousands of rows this is not observable, but it
  would be the wrong architecture for a dataset many orders of magnitude
  larger.
- Bulk analytics questions ("what's the distribution of fractional
  quantities") that pandas makes a one-liner have to be answered
  separately, in the standalone profiling script behind
  `tests/e2e/expected_counts.json`, rather than by reusing ingest-path
  code.
