# ADR-014: Decimal ORM mapping for quantities and prices

Status: Accepted
Date: 2026-08-16

## Context

ADR-008 mandates that inventory quantities be stored exactly as given,
preserving fractional values (`16.4`) rather than rounding them, because
the fractional part is plausible real information rather than noise.
Prices (`purchase_price`, `suggested_retail_price`, `profit_margin`) carry
the same "exact stored value matters" property — money should never be
represented in a way that introduces silent rounding error. Every numeric
column that represents a quantity or a monetary value therefore needs an
ORM mapping decision, since Python's native `float` and SQLAlchemy's
default numeric mapping are not, by themselves, exact.

## Options Considered

- **`Numeric`/`Decimal` mapping (chosen)** — Every quantity and price
  column is declared as SQLAlchemy `Numeric(precision, scale)` and mapped
  to Python's `decimal.Decimal` (`Mapped[Decimal] = mapped_column(Numeric(...))`,
  e.g. `Numeric(12, 3)` for inventory quantity, `Numeric(10, 2)` for
  prices). `Decimal` arithmetic is exact for base-10 values like money and
  the pieces-with-one-decimal-place quantities in this dataset — no
  representation error accumulates through repeated storage and retrieval.
  This directly satisfies ADR-008's "stored exactly as given" requirement
  and is the standard, well-understood approach for monetary values in any
  language with a decimal type.
- **`float` mapping** — Simpler on the surface (native Python `float`,
  no `Decimal` import needed anywhere), but `float` is IEEE-754 binary
  floating point, which cannot represent most base-10 fractions (including
  common money values like `0.10`) exactly. Storing `16.4` as a float and
  reading it back is not guaranteed to yield a value that compares equal
  to the original decimal literal — a real risk for a dataset ADR-008
  explicitly says must be preserved exactly, and an unacceptable one for
  money, where accumulated float error is a classic, well-documented class
  of financial-software bug. Rejected as lossy by construction, which
  directly contradicts ADR-008's premise.
- **String storage** — Store the raw text value as-is (e.g. the literal
  string `"16.4"`), sidestepping any numeric representation question
  entirely. This does preserve the exact source text, but it pushes
  parsing and arithmetic (rounding for display, comparisons, any future
  aggregation) into every consumer of the column instead of doing it once
  at the ORM boundary, and SQL-level numeric operations (e.g. an `ORDER BY
  quantity` that behaves numerically, not lexicographically) stop working
  correctly against a text column. It trades a solved problem (exact
  decimal storage, which `Numeric`/`Decimal` already handles) for a
  harder one (re-deriving numeric semantics from text everywhere the
  value is used).

## Decision

Map every quantity and price column to `Mapped[Decimal]` backed by a
SQLAlchemy `Numeric(precision, scale)` column: `items.purchase_price` /
`items.suggested_retail_price` (`Numeric(10, 2)`),
`inventory_records.quantity` (`Numeric(12, 3)`),
`orderable_items.purchase_price` / `suggested_retail_price`
(`Numeric(10, 2)`) / `profit_margin` (`Numeric(8, 4)`). Pydantic response
schemas at the API boundary (`app/schemas/recommendations.py`) expose these
as JSON numbers (`float`) in the HTTP response, since JSON has no native
decimal type and API consumers overwhelmingly expect plain numeric fields —
the exact `Decimal` value lives in the database and in the ORM layer; the
API boundary is where, and only where, the value becomes a `float` for
serialization.

## Consequences

**Positive:**

- Storage and application-layer arithmetic are exact for both money and
  the fractional inventory quantities ADR-008 requires be preserved —
  there is no accumulated floating-point drift anywhere between the CSV
  value and the database value.
- `mypy --strict` distinguishes `Decimal`-typed ORM attributes from
  `float`-typed schema fields at the type level, so a future change that
  accidentally mixes the two (e.g. passing a raw `Decimal` into a
  `float`-typed Pydantic field without an explicit conversion) is a type
  error caught before runtime, not a silent precision bug.
- Matches standard practice for monetary and precision-sensitive
  quantities in typed application code, so the design needs no
  special-case justification for a reviewer familiar with the pattern.

**Negative:**

- `Decimal` values must be explicitly converted (`float(...)`) at the
  Pydantic-schema boundary, since `float` is what a JSON API response
  naturally represents — this means the API's public numbers are lossy
  relative to the exact stored values, by design (documented here so it
  is a deliberate boundary decision, not an oversight): a client reading
  `purchase_price: 1.2` from the API is reading a `float`, not the exact
  stored `Decimal`, even though the database itself never loses precision.
- `Decimal` arithmetic and comparisons are slightly more verbose in
  application code than native numeric types (explicit `Decimal(...)`
  construction from strings, not float literals, to avoid reintroducing
  the exact problem this ADR avoids), which is a minor ergonomic cost
  throughout `app/ingest/normalize.py` and anywhere quantities or prices
  are manipulated.
