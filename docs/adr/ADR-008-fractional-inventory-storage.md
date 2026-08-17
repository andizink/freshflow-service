# ADR-008: Fractional inventory storage

Status: Accepted
Date: 2026-08-16

## Context

`inventory.csv`'s `quantity` column contains ~22,400 fractional values such
as `16.4` pieces, roughly 87% of the file, despite quantities being
documented elsewhere as whole pieces. That is far too large and too
systematic to be noise. It is much more likely a real signal — weight-based
items sold by the piece-equivalent, partial-crate accounting, or similar —
than tens of thousands of independent data-entry errors. The ingest and
storage design has to decide whether that fractional information is
preserved, discarded, or rejected.

## Options Considered

- **Store exactly as Decimal, expose rounded int at the API boundary
  (chosen)** — The quantity is parsed and persisted as an exact `Decimal`
  (`Numeric(12, 3)` column, see ADR-014), preserving every digit the source
  file provided. The ingest report counts these rows under a
  `fractional_quantity` warning, so the anomaly is visible without being
  treated as an error. The API's `current_inventory` field presents a
  half-up-rounded integer, because the recommendations response is meant to
  be a readable "roughly how much is on the shelf" figure rather than a raw
  database dump. Nothing is lost in the database; rounding happens only at
  presentation time.
- **Round at ingest (store as integer)** — Would match the "whole pieces"
  documentation and simplify the schema to an `int` column, but destroys
  the fractional information permanently the moment the row is written. The
  original `16.4` could never be recovered, even if it later turned out to
  matter for a stock reconciliation. With fractional values at 87% of the
  file, this discards the majority of one file's actual content on a guess
  about what it "should" have been.
- **Quarantine all fractional-quantity rows** — Treats the fractional value
  as a defect serious enough to exclude the row. Rejected because it would
  discard ~22,000 rows of plausibly legitimate business data, and because,
  unlike a negative quantity or an unparseable date, nothing about a
  fractional inventory count is actually invalid. It just doesn't match an
  informal expectation stated elsewhere.

## Decision

Parse inventory `quantity` as an exact `Decimal`
(`app.ingest.normalize.parse_quantity`), store it unmodified in the
`inventory_records.quantity` column (`Numeric(12, 3)`), count every
fractional occurrence as a `fractional_quantity` warning in the ingest
report (not a quarantine reason), and round half-up to the nearest integer
only when building the `current_inventory` field of the recommendations API
response.

## Consequences

No information from the source file is ever destroyed: the exact value a
store's system reported stays recoverable from the database even though the
API surfaces a rounded figure. The ingest report makes the anomaly (87%
fractional) visible to whoever owns the upstream data instead of hiding it
behind a silent round or an equally silent mass rejection, and all of
`inventory.csv` stays usable.

The trade-offs:

- The schema is more complex than a plain integer column would be
  (`Decimal`/`Numeric` throughout the ORM and query layer, per ADR-014),
  and every consumer of `quantity` has to be deliberate about needing the
  exact value versus the rounded display value.
- The API boundary now carries two representations of the same underlying
  fact: exact `Decimal` in the database, rounded `int` in the response.
  That has to be documented clearly so consumers don't mistake
  `current_inventory` for the precise stored value.
