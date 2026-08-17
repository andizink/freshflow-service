# ADR-014: Decimal ORM mapping for quantities and prices

Status: Accepted
Date: 2026-08-16

## Context

ADR-008 requires that inventory quantities be stored exactly as given,
preserving fractional values like `16.4` rather than rounding them, because
the fractional part is plausible real information rather than noise. Prices
(`purchase_price`, `suggested_retail_price`, `profit_margin`) have the same
"exact stored value matters" property; money should never be represented in
a way that introduces silent rounding error. Every numeric column
representing a quantity or a monetary value therefore needs an explicit ORM
mapping decision, since Python's native `float` and SQLAlchemy's default
numeric mapping are not, by themselves, exact.

## Options Considered

- **`Numeric`/`Decimal` mapping (chosen)** — Every quantity and price
  column is declared as SQLAlchemy `Numeric(precision, scale)` and mapped
  to `decimal.Decimal`
  (`Mapped[Decimal] = mapped_column(Numeric(...))`, e.g. `Numeric(12, 3)`
  for inventory quantity, `Numeric(10, 2)` for prices). `Decimal`
  arithmetic is exact for base-10 values like money and the
  one-decimal-place quantities in this dataset, so no representation error
  accumulates through repeated storage and retrieval. This satisfies
  ADR-008's "stored exactly as given" requirement and is the standard
  approach for monetary values in any language with a decimal type.
- **`float` mapping** — Simpler on the surface, with no `Decimal` import
  needed anywhere, but `float` is IEEE-754 binary floating point and cannot
  represent most base-10 fractions exactly, including common money values
  like `0.10`. Storing `16.4` as a float and reading it back is not
  guaranteed to compare equal to the original decimal literal. That is a
  real risk for a dataset ADR-008 says must be preserved exactly, and an
  unacceptable one for money, where accumulated float error is a classic
  financial-software bug. Lossy by construction, which contradicts
  ADR-008's premise.
- **String storage** — Store the raw text (`"16.4"`) and sidestep numeric
  representation entirely. It does preserve the exact source text, but it
  pushes parsing and arithmetic — rounding for display, comparisons, any
  future aggregation — into every consumer of the column instead of doing
  it once at the ORM boundary. SQL-level numeric operations stop behaving
  numerically too: `ORDER BY quantity` on a text column sorts
  lexicographically. It trades a solved problem for a harder one.

## Decision

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

Storage and application-layer arithmetic are exact for both money and the
fractional inventory quantities ADR-008 requires, with no floating-point
drift anywhere between the CSV value and the database value. `mypy
--strict` also distinguishes `Decimal`-typed ORM attributes from
`float`-typed schema fields, so a future change that mixes the two — say,
passing a raw `Decimal` into a `float`-typed Pydantic field without an
explicit conversion — is a type error caught before runtime rather than a
silent precision bug. The pattern is standard enough that it needs no
special-case justification for a reviewer who has seen it before.

What it costs:

- `Decimal` values must be explicitly converted with `float(...)` at the
  Pydantic-schema boundary, so the API's public numbers are lossy relative
  to the exact stored values. That is a deliberate boundary decision,
  documented here so it doesn't read as an oversight: a client reading
  `purchase_price: 1.2` is reading a `float`, even though the database
  itself never loses precision.
- `Decimal` arithmetic is slightly more verbose in application code than
  native numeric types, including constructing `Decimal(...)` from strings
  rather than float literals to avoid reintroducing the exact problem this
  ADR avoids. A minor ergonomic cost in `app/ingest/normalize.py` and
  anywhere quantities or prices are manipulated.
