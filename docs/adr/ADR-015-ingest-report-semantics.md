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
- A quarantined row was still parsed and classified by `process_row` — does
  it contribute to `normalizations`/`warnings` even though it never reaches
  the database?
- Q4 (`conflicting_duplicate`): when two rows share a key but disagree on
  values, the first occurrence stays loaded (§ADR — see `ingest_dataset`
  docstring) and *both* raw versions are archived to `quarantine_rows`.
  That means one row is simultaneously present in `loaded_rows` and in
  `quarantined_rows`. Is that a bug, or an intentional invariant a reader
  of the report needs to know about?

These are implementation decisions already made in `app/ingest/service.py`
and `app/ingest/rules.py` — this ADR records them explicitly so the
semantics are traceable to a decision, not just inferable from reading the
loop, and so `docs/DATA_GUIDE.md` / `docs/DATA_QUALITY.md` can cite a fixed
point of truth for numbers that otherwise look inconsistent at first glance
(e.g. D2: 1,994 raw float-form item numbers in `order_recommendations.csv`
vs. 1,916 counted as `item_number_float_coerced`).

## Options Considered

- **Value-level counters that include rows later dropped as duplicates
  (chosen)** — `process_row` counts one increment per *value* repaired
  (`ctx.count(...)` is called once per column, so a row with two repaired
  columns adds two to the totals), and those counts are merged into the
  running report totals immediately after `process_row` returns — *before*
  the caller checks whether the row's key was already seen. This means a
  row that normalizes cleanly but then turns out to be an exact duplicate
  (N7, silently dropped) or a conflicting duplicate (Q4, quarantined) still
  contributes its normalization counts: it *was* processed and repaired,
  even though it didn't end up as one of the final loaded rows. Quarantined
  rows (Q1/Q2/Q3/Q5, rejected inside `process_row` itself) contribute
  nothing, because `ProcessedRow.values is None` short-circuits before any
  repair for that row is "real" — there is no loaded value to have been
  repaired.
- **Row-level counters (rejected)** — Count one increment per row that had
  *any* repair applied, regardless of how many columns changed. Simpler to
  read, but throws away information: a report saying "40 rows repaired"
  can't distinguish one column-wide defect hitting 40 rows from four
  different defects each hitting 10 rows, which matters when an operator
  is trying to decide which upstream system to fix first. `DATA_GUIDE.md`
  and `DATA_QUALITY.md` already document counters as per-value (e.g. N4/N5
  "counted independently... a row with two stripped cells counts twice"),
  so row-level counting would also contradict documentation written before
  this ADR and require rewriting it.
- **Exclude rows later dropped as duplicates from the counters** — Only
  count a repair once the row is known to survive dedup, i.e. defer
  counting until after the `seen`-key check. This is arguably more
  intuitive ("only count what actually got loaded"), but requires a
  two-pass structure (or buffering every row's counts until its dedup fate
  is known, then reconciling), and it still leaves an inconsistency:
  Q4-conflicting rows are quarantined but the *first* occurrence at that
  key is loaded, so "did this key's repair count?" would depend on
  processing order in a way that is not reproducible from the CSV alone
  (row order is incidental, not part of the data's meaning). The chosen
  design avoids this entirely by counting at process time, independent of
  what happens to the row afterward.
- **Q4 all-quarantined (both versions rejected, neither loaded)** —
  Instead of keeping the first occurrence loaded and archiving both raw
  versions, reject every row that shares a key with a conflicting payload,
  including the first. This is simpler to reason about (no row is
  simultaneously "loaded" and "quarantined") but throws away usable data:
  the first occurrence passed every other rule and has no defect of its
  own — only a *later* row disagreeing with it. In this dataset Q4 never
  actually fires (every duplicate key's rows are byte-identical — see
  `docs/DATA_GUIDE.md` §3.1), but the rule exists for robustness against
  future data, and discarding a perfectly valid row because a later row
  contradicts it is a worse default than keeping the row and flagging the
  conflict.

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
   conflict (quarantined) still counts toward `normalizations` — it *was*
   processed and its repair *did* happen, independent of whether the row
   itself ends up in the final loaded set. This is why, for example,
   `item_number_float_coerced` (1,916) is close to but not identical to the
   raw count of float-form item numbers in `order_recommendations.csv`
   (1,994): the gap is rows that failed a *different* rule (Q1/Q2) on the
   same row and were rejected inside `process_row` before reaching the
   counter — not rows dropped by dedup, which *do* still count.

3. **Quarantined rows (Q1/Q2/Q3/Q5) contribute nothing to
   `normalizations`/`warnings`.** `process_row` returns
   `ProcessedRow(values=None, reasons=...)` for a rejected row, with
   `normalizations`/`warnings` left at their dataclass defaults (empty
   dicts) — there is no repair to report for a row that is not going to be
   part of the loaded data. The report's normalization/warning totals
   therefore answer "what did we change about the data we kept (or at
   least attempted to keep before a later duplicate check ran)?", not
   "what did we notice about every row we ever looked at?".

4. **Q4 conflicting duplicates: first occurrence loaded *and* archived to
   quarantine (double bookkeeping).** When a later row shares a key with an
   already-loaded row but disagrees on values, the first occurrence stays
   in `loaded_rows` (it passed every rule and nothing about it individually
   is wrong) and *both* its raw row and the conflicting row's raw row are
   copied into `quarantine_rows` with reason `conflicting_duplicate`. This
   keeps two invariants simultaneously satisfiable:
   `received_rows == loaded_rows + deduplicated_rows + rows_rejected`
   stays reconcilable from the report alone, while `quarantine_rows` (and
   `quarantined_rows` in the report) remains a *complete* audit set — an
   auditor can always find every raw row version that was ever in conflict,
   including the one that "won" and got loaded, without having to
   cross-reference the live table separately. `quarantined_rows` is
   therefore `rows_rejected` plus one bonus entry per distinct key that had
   at least one conflict, which is documented explicitly in
   `ingest_dataset`'s docstring so the arithmetic is never a surprise.

5. **The `normalizations` object is zero-filled from a fixed key
   vocabulary** (`rules.NORMALIZATION_KEYS`): every report contains all
   five counter keys, with `0` for counters that never fired. Consumers
   never have to distinguish an absent key from a zero count, and the
   report shape matches the specification's example exactly. (An earlier
   iteration emitted a sparse dict; the adversarial review flagged the
   mismatch with the spec example and the sparse form was replaced.)
   `quarantine_summary`, by contrast, stays sparse deliberately: its key
   space is open-ended (reason codes may grow), and an empty object already
   communicates "nothing quarantined" unambiguously.

## Consequences

**Positive:**

- Every number in `IngestReport` has one unambiguous meaning, stated once
  here, that `docs/DATA_GUIDE.md`/`docs/DATA_QUALITY.md` and the code's own
  docstrings can point to instead of re-deriving or (worse) silently
  disagreeing about it.
- Value-level counting gives the uploader the most actionable signal: "12
  cells needed whitespace stripped" is more useful for deciding whether to
  fix an upstream exporter than "6 rows had something stripped."
- The Q4 double-bookkeeping choice means no audit question ("what was ever
  in conflict at this key?") requires joining `quarantine_rows` against the
  live table — the quarantine table alone is a complete answer.

**Negative:**

- The counting rules are not fully derivable by staring at the top-level
  report numbers alone — e.g. `item_number_float_coerced` (1,916) doesn't
  equal the raw defect count (1,994) without knowing rule 2/3 above, and
  `quarantined_rows` can exceed `rows_rejected` without knowing rule 4.
  This ADR, and the `ingest_dataset` docstring it mirrors, are the
  authoritative explanation; anyone diffing "measured at profiling" numbers
  against "counted in the report" numbers needs to read one of the two.
- Counting values instead of rows means a single badly-formatted upstream
  column (e.g. every `category` cell in one export batch is upper-cased)
  can dominate a normalization total in a way that looks alarming at a
  glance even though it is one root cause, not many independent defects —
  mitigated by the per-name breakdown (the count is attributed to
  `casing_normalized` specifically, not buried in a single aggregate).
