# ADR-003: Ingestion strategy

Status: Accepted
Date: 2026-08-16

## Context

Profiling the four challenge CSVs (see `docs/DATA_QUALITY.md`) found
systematic, non-trivial defects in every file: inconsistent store-ID
spelling, float-formatted item numbers, mixed date formats, fractional
inventory quantities, negative recommended quantities, references to items
missing from the catalog, exact-duplicate rows, and casing/whitespace noise.
None of the four files is clean, and the defects are large in absolute
terms (hundreds to tens of thousands of rows per defect class). Any ingest
design has to take an explicit position on what happens to a row it cannot
trust at face value; there is no neutral default.

## Options Considered

- **Normalize + quarantine (chosen, user-confirmed)** — Deterministic rules
  repair defects with exactly one reasonable interpretation (e.g. trim and
  lowercase a store ID) and set aside rows that would otherwise require
  guessing (e.g. a negative quantity), storing them raw with a reason code
  for audit. This maximizes usable data while keeping every decision
  documented and reversible (re-ingesting a corrected upstream file can
  recover previously quarantined rows). The cost is real: this is
  meaningfully more code than either alternative, and every defect class
  needs its own explicit, tested policy rather than one blanket rule.
- **Strict reject-file** — Reject the entire file if any row is invalid.
  This has an appealing, simple contract ("the file is clean or it isn't"),
  but given the measured defect rates in these files (for example, ~87% of
  `inventory.csv` rows carry fractional quantities), a strict policy would
  reject every file in its entirety. The service would never successfully
  ingest anything, which is a worse outcome than doing nothing at all — it
  actively hides that a viable subset of the data is fine.
- **Load as-is, clean on read** — Store rows verbatim and apply cleaning
  logic in every query path instead of at ingest time. This is fast to
  build initially, but the cleaning logic (store-ID canonicalization, date
  parsing, dedup) would have to be duplicated wherever the data is read,
  and the database would permanently contain garbage rows (negative
  quantities, orphaned item references) that every future query, report,
  or export has to remember to filter out. It also makes "how many bad
  rows were in the last upload" impossible to answer directly from the
  live tables.

## Decision

Adopt **normalize + quarantine**, applied once at ingest time
(`app/ingest/service.py` orchestrating `app/ingest/normalize.py` and
`app/ingest/rules.py`). A row is either loaded (possibly after a documented
repair), loaded with a warning attached to the ingest report, or quarantined
with a reason code and its raw payload preserved for audit
(`quarantine_rows` table, ADR-010). The live tables (`items`, `inventory`,
`orderable_items`, `order_recommendations`) therefore only ever contain data
the query layer can trust without re-checking it.

## Consequences

**Positive:**

- Query code (`app/recommendations/service.py`, `app/stores/router.py`)
  never has to re-validate or re-clean data — it can assume every row in a
  live table is trustworthy.
- Every ingest run produces a complete, auditable record of what happened
  to the data (`IngestReport`), which is required both for the challenge's
  transparency expectations and for anyone debugging "why is this row
  missing."
- Quarantine is reversible: fixing the upstream data source and
  re-ingesting recovers previously excluded rows, because nothing is
  destroyed, only set aside.
- Maximizes the fraction of real, usable data that makes it into the
  system relative to a strict reject-file policy, which here would yield
  zero usable data.

**Negative:**

- This is the most code-intensive of the three options: every defect class
  needs its own rule, its own reason code, its own unit test, and its own
  line in the ingest report — there is no shortcut.
- The rules are a genuine policy surface (what counts as "unambiguous"
  enough to repair) that must be documented and defended, not just
  implemented; getting a rule wrong silently corrupts data in a way that
  is harder to notice than an outright rejection would be.
- Two categories of "not loaded" exist (quarantined vs. loaded-with-a-note)
  and consumers of the API must understand the distinction to interpret
  the ingest report correctly.
