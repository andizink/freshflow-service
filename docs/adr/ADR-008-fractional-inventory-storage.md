# ADR-008: Fractional inventory storage and exact Decimal mapping

Status: Accepted
Date: 2026-08-16

> Note: this record absorbs former ADR-014 (Decimal ORM mapping), merged in
> the pre-submission editorial pass because the two records documented one
> decision — exactness — at two layers (ingest rule and storage mapping).
> The ADR numbering keeps its gap; nothing was renumbered.

## Context

`inventory.csv`'s `quantity` column contains ~22,400 fractional values such
as `16.4` pieces, roughly 87% of the file, despite quantities being
documented elsewhere as whole pieces. That is far too large and too
systematic to be noise. It is much more likely a real signal — weight-based
items sold by the piece-equivalent, partial-crate accounting, or similar —
than tens of thousands of independent data-entry errors. The ingest and
storage design has to decide whether that fractional information is
preserved, discarded, or rejected.

The same "exact stored value matters" property applies to money
(`purchase_price`, `suggested_retail_price`, `profit_margin`): money should
never be represented in a way that introduces silent rounding error, so
every numeric column representing a quantity or a monetary value needs an
explicit representation decision — Python's native `float` and SQLAlchemy's
default numeric mapping are not, by themselves, exact.

## Options Considered

- **Store exactly as Decimal, expose rounded int at the API boundary
  (chosen)** — The quantity is parsed and persisted as an exact `Decimal`
  (`Numeric(12, 3)` column, see Decision below), preserving every digit the
  source file provided. The ingest report counts these rows under a
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

For the storage representation itself (quantities *and* prices):

- **`Numeric`/`Decimal` mapping (chosen)** — Every quantity and price
  column is declared as SQLAlchemy `Numeric(precision, scale)` and mapped
  to `decimal.Decimal` (`Mapped[Decimal] = mapped_column(Numeric(...))`).
  `Decimal` arithmetic is exact for base-10 values like money and the
  one-decimal-place quantities in this dataset, so no representation error
  accumulates through repeated storage and retrieval. This is the standard
  approach for monetary values in any language with a decimal type.
- **`float` mapping** — Simpler on the surface, but `float` is IEEE-754
  binary floating point and cannot represent most base-10 fractions
  exactly, including common money values like `0.10`. Storing `16.4` as a
  float and reading it back is not guaranteed to compare equal to the
  original decimal literal. Lossy by construction, which contradicts this
  ADR's premise, and a classic source of accumulated financial-software
  error.
- **String storage** — Preserves the exact source text (`"16.4"`) but
  pushes parsing and arithmetic — rounding for display, comparisons, any
  future aggregation — into every consumer of the column instead of doing
  it once at the ORM boundary, and SQL-level numeric operations stop
  behaving numerically (`ORDER BY quantity` sorts lexicographically). It
  trades a solved problem for a harder one.

## Decision

Parse inventory `quantity` as an exact `Decimal`
(`app.ingest.normalize.parse_quantity`), store it unmodified, count every
fractional occurrence as a `fractional_quantity` warning in the ingest
report (not a quarantine reason), and round half-up to the nearest integer
only when building the `current_inventory` field of the recommendations API
response.

Map every quantity and price column to `Mapped[Decimal]` backed by a
SQLAlchemy `Numeric(precision, scale)` column: `items.purchase_price` /
`items.suggested_retail_price` (`Numeric(10, 2)`),
`inventory_records.quantity` (`Numeric(12, 3)`),
`orderable_items.purchase_price` / `suggested_retail_price`
(`Numeric(10, 2)`) / `profit_margin` (`Numeric(8, 4)`). Pydantic response
schemas at the API boundary (`app/schemas/recommendations.py`) expose these
as JSON numbers (`float`), since JSON has no native decimal type and API
consumers overwhelmingly expect plain numeric fields. The exact `Decimal`
lives in the database and the ORM layer; the API boundary is where, and
only where, it becomes a `float` for serialization.

## Consequences

No information from the source file is ever destroyed: the exact value a
store's system reported stays recoverable from the database even though the
API surfaces a rounded figure. The ingest report makes the anomaly (87%
fractional) visible to whoever owns the upstream data instead of hiding it
behind a silent round or an equally silent mass rejection, and all of
`inventory.csv` stays usable. Storage and application-layer arithmetic are
exact for both money and quantities, with no floating-point drift anywhere
between the CSV value and the database value; `mypy --strict` also
distinguishes `Decimal`-typed ORM attributes from `float`-typed schema
fields, so mixing the two without an explicit conversion is a type error
caught before runtime rather than a silent precision bug.

The trade-offs:

- The schema is more complex than plain integer/float columns would be
  (`Decimal`/`Numeric` throughout the ORM and query layer), and every
  consumer of `quantity` has to be deliberate about needing the exact value
  versus the rounded display value.
- The API boundary now carries two representations of the same underlying
  fact: exact `Decimal` in the database, rounded/`float` values in the
  response. A client reading `purchase_price: 1.2` is reading a `float`,
  even though the database itself never loses precision — a deliberate
  boundary decision, documented here so it doesn't read as an oversight.
- `Decimal` arithmetic is slightly more verbose in application code,
  including constructing `Decimal(...)` from strings rather than float
  literals to avoid reintroducing the exact problem this ADR avoids.
