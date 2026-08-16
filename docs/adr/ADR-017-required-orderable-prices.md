# ADR-017: purchase_price is required on orderable windows

Status: Accepted
Date: 2026-08-16

## Context

`orderable_items.csv` contains 1,299 rows (5% of the file) with an empty
`purchase_price` — the same rows also carry an empty `profit_margin`
(defect **D10** in `docs/DATA_QUALITY.md`). The ingest pipeline had to
decide whether a purchasable window without a purchase price is usable
data. An orderable window's whole purpose is to tell a store *what it can
order and at what cost*: downstream, the window's prices override the
catalog prices in recommendation responses, and the margin is derived from
them. `profit_margin`, by contrast, is a derived convenience value.

## Options Considered

### Option A — require `purchase_price`, quarantine rows without it (chosen)

- Pro: a window without a cost cannot support an ordering decision — loading
  it would surface `null` prices in enriched responses exactly where the
  caller expects the authoritative window price.
- Pro: quarantine is reversible by design; if a corrected export arrives,
  re-ingest recovers all 1,299 rows.
- Pro: consistent with the project's one-sentence rule ("if a reasonable
  colleague could disagree about the correct value, quarantine and
  report") — there is no defensible way to invent a missing cost.
- Con: 1,299 otherwise well-formed rows are excluded from the loaded set,
  which also inflates the "recommendations without a window" warning count
  (see D9's reconciliation note in `docs/DATA_QUALITY.md`).

### Option B — make the column nullable and load the rows

- Pro: maximizes loaded data; the recommendation join could fall back to
  catalog prices.
- Con: silently degrades the price-override contract — the API would claim
  a window exists while substituting a price from a different source, which
  is precisely the kind of quiet guessing the ingest philosophy forbids.
- Con: `NULL` costs propagate into margin calculations downstream.

### Option C — impute the price from the catalog or neighboring windows

- Pro: keeps the rows and produces plausible numbers.
- Con: invents data; the imputed value would be indistinguishable from a
  supplier-quoted price to every consumer. Rejected on principle.

## Decision

`purchase_price` (and `suggested_retail_price`) are required fields on
`orderable-items` rows; rows missing them are quarantined with reason
`missing_field`. `profit_margin` stays nullable (derived, not
load-bearing). Implemented in `app.ingest.rules._build_orderable_items`;
pinned by the D10 fixtures and the e2e expected counts (1,299
`missing_field` quarantines on the real file).

## Consequences

- Positive: every loaded window is guaranteed priceable; the price
  override in `GET .../recommendations` never serves a guessed value.
- Positive: the upstream export bug is visible in every ingest report
  instead of being absorbed.
- Negative: loaded-set cross-file gaps (D9's 1,223 warning) are larger than
  the raw-data gap (327) until the upstream data is fixed; the
  reconciliation is documented so the numbers don't look contradictory.
