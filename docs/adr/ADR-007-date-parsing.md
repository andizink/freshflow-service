# ADR-007: Slash-date interpretation (day-first)

Status: Accepted
Date: 2026-08-16

## Context

`inventory.csv` contains 803 dates in slash notation (e.g. `23/01/2024`)
mixed into a column that otherwise holds ISO `YYYY-MM-DD` dates.
Slash-separated dates are inherently ambiguous between day-first and
month-first conventions whenever both components could plausibly be a month:
`01/05/2024` could mean 1 May or 5 January. Every row in this format needs a
single, defensible, deterministic interpretation, because guessing wrong
silently shows a recommendation on the wrong calendar day, which is a worse
failure than dropping the row.

## Options Considered

- **Day-first (`DD/MM/YYYY`), chosen** — The data resolves the ambiguity
  itself. Values such as `23/01/2024` and `31/12/2024` appear in the file;
  there is no 23rd month and no 31st month, so any date whose first
  component exceeds 12 can only be a day. The format convention is a
  property of the exporting system rather than of an individual row, so the
  same convention is assumed to apply uniformly across every slash date in
  the column, including the ambiguous ones. That is an inference from
  evidence, not a coin flip.
- **Month-first (`MM/DD/YYYY`)** — The conventional US format, and directly
  refuted by the data: `23/01/2024` cannot be parsed as `MM/DD/YYYY`. Not
  merely less likely, but falsified for 803 rows' worth of the exporting
  system's actual behavior.
- **Reject all slash-formatted dates** — The "safe" option: quarantine
  every ambiguous date rather than guess. Rejected because the ambiguity is
  resolved by evidence in this specific case, and quarantining all 803 rows
  would discard correctly interpretable data over an ambiguity that, on
  inspection, doesn't exist for this file.

## Decision

`app.ingest.normalize.parse_day` attempts ISO `YYYY-MM-DD` first, then falls
back to day-first `DD/MM/YYYY` for any value that doesn't parse as ISO. A
value matching neither format is quarantined under `invalid_value` (Q3),
not guessed at.

## Consequences

803 rows that would otherwise be ambiguous or need manual review are
recoverable and correctly dated, backed by direct evidence in the data
rather than an assumption. The interpretation is uniform and deterministic
across the whole column, which is what a single exporting system's format
convention implies, and there is no per-row guessing logic to get subtly
wrong.

The risk we are accepting: the day-first inference generalizes from the
subset of dates where the ambiguity happens to be resolvable (day component
> 12) to the full set of slash dates, including those where both readings
would be syntactically valid, such as `01/05/2024`. If a future data source
mixed both conventions inside one column, this single global rule would
silently misparse the minority convention. There is no evidence of mixed
conventions in the profiled data, and it is documented here so a later
data-quality audit knows exactly what was assumed.
