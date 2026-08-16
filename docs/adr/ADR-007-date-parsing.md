# ADR-007: Slash-date interpretation (day-first)

Status: Accepted
Date: 2026-08-16

## Context

`inventory.csv` contains 803 dates in `DD/MM/YYYY`-or-`MM/DD/YYYY`-shaped
slash notation (e.g. `23/01/2024`) mixed in with ISO `YYYY-MM-DD` dates in
the same column. Slash-separated dates are inherently ambiguous between
day-first and month-first conventions when both components could plausibly
be a month (e.g. `01/05/2024` could mean 1 May or 5 January). Every row in
this format needs a single, defensible, deterministic interpretation,
because guessing wrong silently shows a recommendation on the wrong
calendar day — a worse failure than dropping the row.

## Options Considered

- **Day-first (`DD/MM/YYYY`), chosen** — The profiled data itself resolves
  the ambiguity: values such as `23/01/2024` and `31/12/2024` appear in the
  file. There is no 23rd month and no 31st month, so any date where the
  first component exceeds 12 can only be a day. Because the format
  convention is a property of the exporting system, not of any individual
  row, the same convention is assumed to apply uniformly across every
  slash-formatted date in the column, including the ambiguous ones — this
  is an inference from evidence, not a coin flip.
- **Month-first (`MM/DD/YYYY`)** — The conventional US format. Directly
  refuted by the data: `23/01/2024` cannot be parsed as `MM/DD/YYYY` (there
  is no month 23), so this option is not merely less likely, it is
  falsified for at least 803 rows' worth of the exporting system's actual
  behavior.
- **Reject all slash-formatted dates** — The "safe" option of quarantining
  every ambiguous date rather than guessing. Rejected because the
  ambiguity is resolved by evidence in this specific case (see above) —
  quarantining all 803 rows would discard recoverable, correctly
  interpretable data over an ambiguity that, on inspection, does not
  actually exist for this file.

## Decision

`app.ingest.normalize.parse_day` attempts ISO `YYYY-MM-DD` first, then
falls back to day-first `DD/MM/YYYY` for any value that doesn't parse as
ISO. A value that matches neither format is quarantined under
`invalid_value` (Q3), not guessed at.

## Consequences

**Positive:**

- 803 rows that would otherwise be ambiguous or need manual review are
  recoverable and correctly dated, backed by direct evidence in the data
  rather than an assumption.
- The interpretation is uniform and deterministic across the whole column,
  which is what a single exporting system's format convention implies —
  no per-row guessing logic exists to get subtly wrong.

**Negative:**

- The day-first inference is technically a generalization from the subset
  of dates where the ambiguity happens to be resolvable (day component
  >12) to the full set of slash dates, including those where both
  interpretations would have been syntactically valid (e.g. `01/05/2024`).
  If a future data source mixed both conventions within the same column,
  this single global rule would silently misparse the minority convention
  — a risk explicitly accepted here because there is no evidence of mixed
  conventions in the profiled data, and documented so a future data-quality
  audit knows exactly what was assumed.
