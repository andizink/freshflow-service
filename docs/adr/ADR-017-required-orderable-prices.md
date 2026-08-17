# ADR-017: purchase_price is required on orderable windows

Status: Accepted
Date: 2026-08-16

## Context

`orderable_items.csv` contains 1,299 rows (5% of the file) with an empty
`purchase_price`. The same rows also carry an empty `profit_margin`
(defect **D10** in `docs/DATA_QUALITY.md`). The ingest pipeline had to
decide whether a purchasable window without a purchase price is usable
data. An orderable window's whole purpose is to tell a store what it can
order and at what cost: downstream, the window's prices override the
catalog prices in recommendation responses, and the margin is derived from
them. `profit_margin`, by contrast, is a derived convenience value.

## Options Considered

### Option A — require `purchase_price`, quarantine rows without it (chosen)

A window without a cost cannot support an ordering decision. Loading it
would surface `null` prices in enriched responses at exactly the point
where the caller expects the authoritative window price. There is no
defensible way to invent a missing cost, which puts this squarely under the
project's one-sentence rule: if a reasonable colleague could disagree about
the correct value, quarantine and report. And the exclusion is not
permanent — quarantine is reversible, so a corrected export recovers all
1,299 rows on re-ingest.

The cost is that 1,299 otherwise well-formed rows are excluded from the
loaded set, which also inflates the "recommendations without a window"
warning count (see D9's reconciliation note in `docs/DATA_QUALITY.md`).

### Option B — make the column nullable and load the rows

Maximizes loaded data, and the recommendation join could fall back to
catalog prices. Rejected: it silently degrades the price-override contract.
The API would claim a window exists while substituting a price from a
different source, which is precisely the quiet guessing the ingest
philosophy forbids. `NULL` costs would also propagate into margin
calculations downstream.

### Option C — impute the price from the catalog or neighboring windows

Keeps the rows and produces plausible numbers. Rejected on principle: it
invents data, and the imputed value would be indistinguishable from a
supplier-quoted price to every consumer.

## Decision

`purchase_price` (and `suggested_retail_price`) are required fields on
`orderable-items` rows; rows missing them are quarantined with reason
`missing_field`. `profit_margin` stays nullable, being derived rather than
load-bearing. Implemented in `app.ingest.rules._build_orderable_items`, and
pinned by the D10 fixtures and the e2e expected counts (1,299
`missing_field` quarantines on the real file).

## Consequences

Every loaded window is guaranteed priceable, so the price override in
`GET .../recommendations` never serves a guessed value, and the upstream
export bug shows up in every ingest report instead of being quietly
absorbed.

The visible side effect is arithmetic: loaded-set cross-file gaps (D9's
1,223 warning) are larger than the raw-data gap (327) until the upstream
data is fixed. The reconciliation is documented so the two numbers don't
look contradictory.
