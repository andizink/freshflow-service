# ADR-010: Quarantine persistence

Status: Accepted
Date: 2026-08-16

## Context

Rows rejected by the quarantine rules (Q1–Q5) still need to be visible to
whoever operates or audits the system — both to explain "why is this row
missing" and to support recovering rows later if the upstream data or
catalog is corrected. The design has to decide how (and whether) rejected
rows are retained after the HTTP response for the triggering upload has
been sent and forgotten.

## Options Considered

- **Persisted as raw row JSON + reason codes, queryable via API (chosen)**
  — Every quarantined row is stored in a `quarantine_rows` table, linked to
  its owning `ingest_jobs` run, with the row's original unmodified values
  (`raw_row`, a JSON object) and the list of reason codes that caused
  rejection. A dedicated endpoint
  (`GET /api/v1/ingest/{ingest_id}/quarantine`) exposes these, paginated,
  for audit. This gives durable, structured, queryable access to exactly
  what was excluded and why, indefinitely — not just at the moment of the
  triggering request.
- **Log-only** — Write quarantine details to the application log stream
  instead of a database table. Cheaper to implement, but logs are
  operationally awkward as an audit trail: they typically rotate or
  expire, aren't queryable with structured filters (e.g. "show me every
  `negative_quantity` row from the last order_recommendations upload"),
  and conflate operational/debug logging with a business record that
  users of the API are meant to be able to retrieve.
- **Reject-file response only** — Return the excluded rows in the ingest
  report's HTTP response body and don't persist them further. This is
  simplest, but the moment the response is received (or the caller doesn't
  save it), the audit trail for that upload is gone — there is no way to
  answer "what got quarantined from last Tuesday's ingest" after the fact,
  which directly contradicts the stated design principle of reporting
  everything and keeping quarantined data queryable for audit
  (PLAN.md §1.2).

## Decision

Persist quarantined rows to the `quarantine_rows` table (raw row JSON +
`ReasonCode` list, foreign-keyed to the triggering `ingest_jobs` row) and
expose them via `GET /api/v1/ingest/{ingest_id}/quarantine`, paginated with
`limit`/`offset`. The row's original, unmodified values are stored — not a
partially-normalized version — so an auditor sees exactly what the source
file contained.

## Consequences

**Positive:**

- Quarantine data survives indefinitely and independently of any single
  HTTP response, so it can be audited, exported, or used to inform a fix
  to the upstream data source at any later time.
- The raw (unmodified) row is preserved, so a human reviewing a
  quarantined row sees precisely what the source file said, with no
  ambiguity about what was changed versus what was rejected.
- Reason codes are structured (`ReasonCode` enum, not free text), so the
  quarantine table can be queried/aggregated programmatically, matching
  the counts already surfaced in `IngestReport.quarantine_summary`.

**Negative:**

- Every quarantined row is a permanent database row; a dataset with
  chronically high defect rates accumulates quarantine history across
  every re-ingest, with no built-in retention/pruning policy — an
  operational concern intentionally left out of scope for this challenge.
- The audit endpoint is additional API surface (schema, pagination,
  tests) that a log-only approach would not have required.
