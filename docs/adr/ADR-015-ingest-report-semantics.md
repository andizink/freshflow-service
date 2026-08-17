# ADR-015: Ingest report counting semantics

Status: Accepted
Date: 2026-08-16

## Context

`IngestReport` (`app/schemas/ingest.py`) exposes four families of numbers
for every upload: `received_rows`, `loaded_rows`, `deduplicated_rows`,
`quarantined_rows`, plus per-name `normalizations` and per-reason-code
`quarantine_summary` maps. `app.ingest.service.ingest_dataset` and
`app.ingest.rules.process_row` make several non-obvious counting decisions
while building these numbers, and each one changes what a number *means* to
whoever reads the report:

- Does `normalizations["casing_normalized"]` count **rows** that were
  re-cased, or **values**? A row with both a re-cased `category` and a
  re-cased tag is one row but two repairs.
- If a row is normalized successfully but then turns out to be an exact
  duplicate of an already-loaded row (N7) and is silently dropped, did its
  repair "happen"? Should it still show up in `normalizations`?
- A quarantined row was still parsed and classified by `process_row`. Does
  it contribute to `normalizations`/`warnings` even though it never reaches
  the database?
- Q4 (`conflicting_duplicate`): when two rows share a key but disagree on
  values, the first occurrence stays loaded (see the `ingest_dataset`
  docstring) and *both* raw versions are archived to `quarantine_rows`.
  That means one row is simultaneously present in `loaded_rows` and in
  `quarantined_rows`. Bug, or an intentional invariant a reader of the
  report needs to know about?

These decisions are already made in `app/ingest/service.py` and
`app/ingest/rules.py`. This ADR records them explicitly so the semantics
are traceable to a decision rather than inferable from reading the loop,
and so `docs/DATA_GUIDE.md` and `docs/DATA_QUALITY.md` can cite a fixed
point of truth for numbers that otherwise look inconsistent at first glance
(D2: 1,994 raw float-form item numbers in `order_recommendations.csv`
vs. 1,916 counted as `item_number_float_coerced`).

## Options Considered

- **Value-level counters that include rows later dropped as duplicates
  (chosen)** — `process_row` counts one increment per *value* repaired
  (`ctx.count(...)` is called once per column, so a row with two repaired
  columns adds two to the totals), and those counts are merged into the
  running report totals immediately after `process_row` returns, *before*
  the caller checks whether the row's key was already seen. So a row that
  normalizes cleanly and then turns out to be an exact duplicate (N7,
  silently dropped) or a conflicting duplicate (Q4, quarantined) still
  contributes its normalization counts: it *was* processed and repaired,
  even if it didn't end up among the final loaded rows. Quarantined rows
  (Q1/Q2/Q3/Q5, rejected inside `process_row` itself) contribute nothing,
  because `ProcessedRow.values is None` short-circuits before any repair
  for that row is real. There is no loaded value to have been repaired.
- **Row-level counters (rejected)** — Count one increment per row that had
  *any* repair applied, regardless of how many columns changed. Simpler to
  read, but it throws away information: "40 rows repaired" can't
  distinguish one column-wide defect hitting 40 rows from four different
  defects hitting 10 rows each, which is exactly what an operator needs to
  decide which upstream system to fix first. `DATA_GUIDE.md` and
  `DATA_QUALITY.md` already document counters as per-value (N4/N5 "counted
  independently... a row with two stripped cells counts twice"), so
  row-level counting would contradict documentation written before this ADR.
- **Exclude rows later dropped as duplicates from the counters** — Only
  count a repair once the row is known to survive dedup, i.e. defer
  counting until after the `seen`-key check. Arguably more intuitive
  ("only count what actually got loaded"), but it needs a two-pass
  structure, or buffering every row's counts until its dedup fate is known,
  and it still leaves an inconsistency. Q4-conflicting rows are quarantined
  while the *first* occurrence at that key is loaded, so "did this key's
  repair count?" would depend on processing order in a way that is not
  reproducible from the CSV alone; row order is incidental, not part of the
  data's meaning. Counting at process time avoids this entirely.
- **Q4 all-quarantined (both versions rejected, neither loaded)** — Reject
  every row that shares a key with a conflicting payload, including the
  first, instead of keeping the first loaded and archiving both raw
  versions. Simpler to reason about, since no row is then both "loaded" and
  "quarantined", but it throws away usable data: the first occurrence
  passed every other rule and has no defect of its own, only a *later* row
  disagreeing with it. Q4 never actually fires in this dataset (every
  duplicate key's rows are byte-identical, see `docs/DATA_GUIDE.md` §3.1),
  but the rule exists for robustness against future data, and discarding a
  valid row because a later row contradicts it is a worse default than
  keeping it and flagging the conflict.

## Decision

1. **Counters count changed *values*, not rows.** `_RowContext.count(name)`
   is called once per column-level repair; a row with two repaired columns
   contributes two to the relevant totals. This applies to every
   normalization counter (`store_id_cleaned`, `item_number_float_coerced`,
   `date_format_converted`, `value_whitespace_stripped`,
   `casing_normalized`) and to the `fractional_quantity` warning counter.

2. **Counters include rows later dropped as duplicates.**
   `_merge_counts(normalizations, processed.normalizations)` and
   `_merge_counts(row_warnings, processed.warnings)` run immediately after
   `process_row` returns, before the dedup/conflict check in
   `ingest_dataset`. A row that repairs cleanly and is then found to be an
   N7 exact duplicate (silently dropped) or the losing side of a Q4
   conflict (quarantined) still counts toward `normalizations`; it *was*
   processed and its repair *did* happen, independent of whether the row
   ends up in the final loaded set. This is why `item_number_float_coerced`
   (1,916) is close to but not identical to the raw count of float-form
   item numbers in `order_recommendations.csv` (1,994). The gap is rows
   that failed a *different* rule (Q1/Q2) on the same row and were rejected
   inside `process_row` before reaching the counter, not rows dropped by
   dedup, which do still count.

3. **Quarantined rows (Q1/Q2/Q3/Q5) contribute nothing to
   `normalizations`/`warnings`.** `process_row` returns
   `ProcessedRow(values=None, reasons=...)` for a rejected row, with
   `normalizations`/`warnings` left at their dataclass defaults (empty
   dicts). There is no repair to report for a row that isn't going to be
   part of the loaded data. The report's normalization and warning totals
   therefore answer "what did we change about the data we kept, or at least
   attempted to keep before a later duplicate check ran?", not "what did we
   notice about every row we ever looked at?".

4. **Q4 conflicting duplicates: first occurrence loaded *and* archived to
   quarantine (double bookkeeping).** When a later row shares a key with an
   already-loaded row but disagrees on values, the first occurrence stays
   in `loaded_rows`, since it passed every rule and nothing about it
   individually is wrong, and *both* its raw row and the conflicting row's
   raw row are copied into `quarantine_rows` with reason
   `conflicting_duplicate`. That keeps two invariants satisfiable at once:
   `received_rows == loaded_rows + deduplicated_rows + rows_rejected`
   stays reconcilable from the report alone, while `quarantine_rows` (and
   `quarantined_rows` in the report) remains a *complete* audit set. An
   auditor can always find every raw row version that was ever in conflict,
   including the one that won and got loaded, without cross-referencing the
   live table. `quarantined_rows` is therefore `rows_rejected` plus one
   bonus entry per distinct key that had at least one conflict, documented
   in `ingest_dataset`'s docstring so the arithmetic is never a surprise.

5. **The `normalizations` object is zero-filled from a fixed key
   vocabulary** (`rules.NORMALIZATION_KEYS`): every report contains all
   five counter keys, with `0` for counters that never fired. Consumers
   never have to distinguish an absent key from a zero count, and the
   report shape matches the specification's example exactly. (An earlier
   iteration emitted a sparse dict; review flagged the mismatch with the
   spec example and the sparse form was replaced.) `quarantine_summary`, by
   contrast, stays sparse on purpose: its key space is open-ended, since
   reason codes may grow, and an empty object already communicates "nothing
   quarantined" unambiguously.

## Consequences

Every number in `IngestReport` now has one unambiguous meaning, stated once
here, that `docs/DATA_GUIDE.md`, `docs/DATA_QUALITY.md` and the code's own
docstrings can point at instead of re-deriving or silently disagreeing
about. Value-level counting also gives the uploader the more actionable
signal: "12 cells needed whitespace stripped" tells you more about whether
to fix an upstream exporter than "6 rows had something stripped." And the
Q4 double-bookkeeping choice means the quarantine table alone answers "what
was ever in conflict at this key?", with no join against the live table.

The cost is that the counting rules are not derivable by staring at the
report:

- `item_number_float_coerced` (1,916) doesn't equal the raw defect count
  (1,994) unless you know rules 2 and 3 above, and `quarantined_rows` can
  exceed `rows_rejected` unless you know rule 4. This ADR and the
  `ingest_dataset` docstring it mirrors are the authoritative explanation;
  anyone diffing "measured at profiling" numbers against "counted in the
  report" numbers needs one of the two.
- Counting values instead of rows means a single badly-formatted upstream
  column — every `category` cell in one export batch upper-cased, say —
  can dominate a normalization total and look alarming at a glance, even
  though it is one root cause rather than many independent defects. The
  per-name breakdown mitigates this: the count is attributed to
  `casing_normalized` specifically, not buried in an aggregate.
