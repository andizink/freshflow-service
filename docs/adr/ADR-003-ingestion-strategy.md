# ADR-003: Ingestion strategy

Status: Accepted
Date: 2026-08-16

## Context

Profiling the four challenge CSVs (see `docs/DATA_QUALITY.md`) found
systematic defects in every file: inconsistent store-ID spelling,
float-formatted item numbers, mixed date formats, fractional inventory
quantities, negative recommended quantities, references to items missing
from the catalog, exact-duplicate rows, casing and whitespace noise. None
of the four files is clean, and the defects are large in absolute terms,
from hundreds to tens of thousands of rows per defect class.

Any ingest design has to take an explicit position on what happens to a row
it cannot trust at face value. There is no neutral default.

## Options Considered

- **Normalize + quarantine (chosen, user-confirmed)** — Deterministic rules
  repair defects with exactly one reasonable interpretation (trim and
  lowercase a store ID) and set aside rows that would otherwise require
  guessing (a negative quantity), storing them raw with a reason code for
  audit. This maximizes usable data while keeping every decision documented
  and reversible: re-ingesting a corrected upstream file recovers
  previously quarantined rows. The cost is real. This is meaningfully more
  code than either alternative, and every defect class needs its own
  explicit, tested policy rather than one blanket rule.
- **Strict reject-file** — Reject the entire file if any row is invalid.
  Appealingly simple as a contract ("the file is clean or it isn't"), but
  given the measured defect rates — ~87% of `inventory.csv` rows carry
  fractional quantities — a strict policy would reject every file in its
  entirety. The service would never successfully ingest anything, which is
  worse than doing nothing at all: it actively hides that a viable subset
  of the data is fine.
- **Load as-is, clean on read** — Store rows verbatim and apply cleaning
  logic in every query path instead. Fast to build initially, but the
  cleaning logic (store-ID canonicalization, date parsing, dedup) gets
  duplicated wherever the data is read, and the database permanently
  contains garbage rows that every future query, report or export has to
  remember to filter out. It also makes "how many bad rows were in the last
  upload" impossible to answer from the live tables.

## Decision

Adopt **normalize + quarantine**, applied once at ingest time
(`app/ingest/service.py` orchestrating `app/ingest/normalize.py` and
`app/ingest/rules.py`). A row is either loaded (possibly after a documented
repair), loaded with a warning attached to the ingest report, or
quarantined with a reason code and its raw payload preserved for audit
(`quarantine_rows` table, ADR-010). The live tables therefore only ever
contain data the query layer can trust without re-checking it.

## Consequences

The payoff is concentrated in the query layer: `app/recommendations/service.py`
and `app/stores/router.py` never re-validate or re-clean anything, because
every row in a live table is already trustworthy. Every ingest run also
produces a complete, auditable record of what happened to the data
(`IngestReport`), which serves both the challenge's transparency
expectations and anyone debugging "why is this row missing." And because
nothing is destroyed, only set aside, quarantine is reversible: fix the
upstream source, re-ingest, and the excluded rows come back.

The costs:

- This is the most code-intensive of the three options. Every defect class
  needs its own rule, reason code, unit test and line in the ingest report.
  There is no shortcut.
- The rules are a policy surface — what counts as "unambiguous" enough to
  repair — that has to be documented and defended, not just implemented.
  Getting a rule wrong corrupts data in a way that is harder to notice than
  an outright rejection would be.
- Two categories of "not loaded" exist, quarantined and
  loaded-with-a-note, and consumers of the API have to understand the
  distinction to read the ingest report correctly.
