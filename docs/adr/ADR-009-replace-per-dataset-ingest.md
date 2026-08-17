# ADR-009: Replace-per-dataset ingest semantics

Status: Accepted
Date: 2026-08-16

## Context

Each of the four datasets may need re-uploading: to correct a data error,
to load a later snapshot, or simply to re-run the demo. The ingest design
has to define what happens to previously loaded rows for that dataset when
a new file arrives. Are they merged with the new data, versioned alongside
it, or replaced outright? The answer determines whether ingest is
idempotent — same file in, same state out, however many times it is
uploaded — and how conflicts between an old and a new upload get resolved.

## Options Considered

- **Replace-per-dataset, atomic transaction (chosen)** — Uploading a file
  for dataset `X` deletes all existing rows for `X` and inserts the newly
  processed rows inside one transaction, so a failure partway through never
  leaves the dataset half-updated: the delete and the insert either both
  commit or neither does. Re-uploading the same file twice produces the
  same end state. This is the simplest semantics to reason about, test and
  document. The price is that no history of a dataset's prior state
  survives, beyond whatever quarantine and report records were already
  persisted for earlier ingest runs.
- **Append/merge semantics** — Merge new rows with existing ones, e.g.
  upsert by natural key. This avoids losing rows present in the old data
  but absent from the new upload, but it immediately raises a question this
  challenge's data does not answer: if the same key appears in both with
  different values, which wins? Any answer is a guess without an explicit
  "supersedes" signal in the source files. The resulting semantics are also
  not naturally idempotent, since re-uploading the same file can
  double-count fresh rows depending on merge-key design.
- **Versioned datasets** — Keep every upload as a separate, timestamped
  generation, with the "current" view resolved by a most-recent rule. This
  is the production-realistic answer for a data source that changes daily,
  and the natural next step if FreshFlow moved beyond a single-shot
  challenge context. It multiplies schema complexity, since every table
  needs a generation dimension, for a requirement (historical diffing
  between uploads) that isn't part of the stated task.

## Decision

Ingest is **replace-per-dataset**: `app.ingest.service.ingest_dataset`
deletes and re-inserts a single dataset's rows inside one database
transaction per upload. Re-uploading a dataset is always idempotent for
identical input and always atomic. The previous generation of that
dataset's rows is either fully replaced or, on any failure, left completely
untouched. Never partially updated.

## Consequences

The semantics are simple and predictable: what's in the database for
dataset X is always exactly what was in the most recently successful upload
for X, with no merge logic to reason about or get wrong. That also makes it
idempotent, which the integration suite verifies directly, and atomic, so a
crashed or interrupted ingest never corrupts previously good data.

Two consequences to keep in mind operationally:

- No history of a dataset's previous state is kept beyond what earlier
  ingest reports and quarantine records captured. There is no way to diff
  "what changed between this upload and the last one" at row level.
- Uploading a partial file for a dataset — say, only one store's rows —
  silently discards the rows previously loaded for the other stores.
  Replace semantics cannot distinguish an intentional partial re-upload
  from an accidentally truncated file. This is documented here rather than
  guarded against in code, since guarding against it needs exactly the kind
  of versioning this ADR declines to build.
