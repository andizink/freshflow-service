# ADR-009: Replace-per-dataset ingest semantics

Status: Accepted
Date: 2026-08-16

## Context

Each of the four datasets may need to be re-uploaded — to correct a data
error, to load a later snapshot, or simply to re-run the demo. The ingest
design must define what happens to previously loaded rows for that dataset
when a new file arrives: are they merged with the new data, versioned
alongside it, or replaced outright? This choice determines whether ingest
is idempotent (same file in, same state out, regardless of how many times
it's uploaded) and how conflicts between an old and a new upload are
resolved.

## Options Considered

- **Replace-per-dataset, atomic transaction (chosen)** — Uploading a file
  for dataset `X` deletes all existing rows for `X` and inserts the newly
  processed rows, inside one transaction, so a failure partway through
  never leaves the dataset half-updated (the delete and the insert either
  both commit or neither does). Re-uploading the exact same file twice
  produces the exact same end state — the operation is idempotent. This is
  the simplest semantics to reason about, test, and document, at the cost
  of not preserving any history of what a dataset looked like before the
  most recent upload (aside from whatever quarantine/report history was
  already persisted for prior ingest runs).
- **Append/merge semantics** — New rows are merged with existing ones
  (e.g. upsert by natural key). This avoids losing rows that exist in the
  old data but not the new upload, but immediately raises an unresolved
  question this challenge's data doesn't answer unambiguously: if the same
  key appears in both the old and new upload with different values, which
  wins? Any answer is a guess without an explicit "supersedes" signal in
  the source files, and the resulting semantics are also not naturally
  idempotent (re-uploading the same file could double-count fresh rows
  that were never seen before, depending on merge-key design).
- **Versioned datasets** (keep every upload as a separate, timestamped
  generation of the data, with the "current" view resolved by a most-recent
  rule) — This is the production-realistic answer for a data source that
  changes daily, and would be the natural next step if FreshFlow moved
  beyond a single-shot demo/challenge context. It's noted as the likely
  production path but is overkill for this challenge: it multiplies schema
  complexity (every table needs a generation/version dimension) for a
  requirement — historical diffing between uploads — that isn't part of
  the stated task.

## Decision

Ingest is **replace-per-dataset**: `app.ingest.service.ingest_dataset`
deletes and re-inserts a single dataset's rows inside one database
transaction per upload. Re-uploading a dataset is always idempotent for
identical input and always atomic — the previous generation of that
dataset's rows is either fully replaced or (on any failure) left
completely untouched, never partially updated.

## Consequences

**Positive:**

- Simple, predictable semantics: "what's in the database for dataset X" is
  always exactly "what was in the most recently successfully uploaded file
  for X" — no merge logic to reason about or get wrong.
- Naturally idempotent: uploading the same file any number of times leaves
  the system in the same state, which the integration test suite verifies
  directly.
- Atomicity means a crashed or interrupted ingest never corrupts previously
  good data — the old rows remain until the new transaction commits in
  full.

**Negative:**

- No history is kept of a dataset's previous state beyond what earlier
  ingest reports and quarantine records already captured — there is no
  way to diff "what changed between this upload and the last one" at the
  row level.
- Uploading a partial or incomplete file for a dataset (e.g. only one
  store's rows) silently discards all rows for the other stores that were
  previously loaded for that dataset, because replace semantics don't
  distinguish "intentional partial re-upload" from "accidentally truncated
  file" — an operational risk documented here rather than guarded against
  in code, since guarding against it would require exactly the kind of
  versioning this ADR declines to build for this challenge.
