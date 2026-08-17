# ADR-010: Quarantine persistence

Status: Accepted
Date: 2026-08-16

## Context

Rows rejected by the quarantine rules (Q1–Q5) still need to be visible to
whoever operates or audits the system, both to explain "why is this row
missing" and to support recovering rows later if the upstream data or the
catalog is corrected. The design has to decide how, and whether, rejected
rows are retained once the HTTP response for the triggering upload has been
sent and forgotten.

## Options Considered

- **Persisted as raw row JSON + reason codes, queryable via API (chosen)**
  — Every quarantined row is stored in a `quarantine_rows` table linked to
  its owning `ingest_jobs` run, with the row's original unmodified values
  (`raw_row`, a JSON object) and the list of reason codes that caused
  rejection. A dedicated endpoint,
  `GET /api/v1/ingest/{ingest_id}/quarantine`, exposes these paginated for
  audit. Durable, structured, queryable access to exactly what was excluded
  and why, indefinitely, rather than only at the moment of the triggering
  request.
- **Log-only** — Write quarantine details to the application log stream
  instead of a table. Cheaper, but logs are an awkward audit trail: they
  rotate or expire, they aren't queryable with structured filters ("show me
  every `negative_quantity` row from the last order_recommendations
  upload"), and they conflate operational logging with a business record
  API users are meant to retrieve.
- **Reject-file response only** — Return the excluded rows in the ingest
  report's HTTP response body and don't persist them. Simplest of all, but
  the audit trail dies the moment the caller drops the response. There
  would be no way to answer "what got quarantined from last Tuesday's
  ingest," which contradicts the stated design principle of reporting
  everything and keeping quarantined data queryable
  ([PLAN.md](../PLAN.md) §1.2).

## Decision

Persist quarantined rows to the `quarantine_rows` table (raw row JSON +
`ReasonCode` list, foreign-keyed to the triggering `ingest_jobs` row) and
expose them via `GET /api/v1/ingest/{ingest_id}/quarantine`, paginated with
`limit`/`offset`. The row's original, unmodified values are stored, not a
partially-normalized version, so an auditor sees exactly what the source
file contained.

## Consequences

Quarantine data survives independently of any single HTTP response, so it
can be audited, exported, or used to drive a fix to the upstream data
source at any later time. Because the raw row is preserved verbatim, a
human reviewing a quarantined row sees precisely what the source file said,
with no ambiguity about what was changed versus what was rejected. Reason
codes are a structured `ReasonCode` enum rather than free text, so the
table can be queried and aggregated programmatically and matches the counts
in `IngestReport.quarantine_summary`.

Costs: every quarantined row is a permanent database row, and a dataset
with chronically high defect rates accumulates quarantine history across
every re-ingest with no built-in retention or pruning policy — an
operational concern intentionally left out of scope here. The audit
endpoint is also additional API surface (schema, pagination, tests) that a
log-only approach would not have needed.
