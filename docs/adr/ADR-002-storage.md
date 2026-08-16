# ADR-002: Storage

Status: Accepted
Date: 2026-08-16

## Context

The service must persist four ingested datasets (~76,000 rows total),
ingest reports, and quarantined rows, and serve queries against them. The
run contract is strict: `docker build` followed by `docker run` must be
sufficient — no `docker-compose`, no external services to provision, no
manual setup steps. The data volume (tens of thousands of rows) is well
within what a single-file embedded database handles comfortably, and the
service does not need concurrent multi-writer throughput; ingest is an
infrequent, replace-per-dataset operation (ADR-009), and recommendation
queries are simple reads.

## Options Considered

- **SQLite via SQLAlchemy 2.0** — Zero external dependencies: the database
  is a file inside the container (optionally on a mounted volume), so the
  "one container, `docker build && docker run`" contract holds trivially.
  SQLite is ACID and more than capable of the read/write patterns this
  service needs at ~75k rows. Its well-known limitation is that it is not a
  true multi-writer database — concurrent write throughput does not scale
  the way a client/server database's does. That is an acceptable trade for
  this workload (occasional bulk replace, frequent light reads) but would
  not be the right choice at real production scale with many concurrent
  ingest clients.
- **PostgreSQL** — The production-realistic choice: proper concurrent
  writes, a mature ecosystem, and what this service would likely migrate to
  if FreshFlow's data volume grew by orders of magnitude. It requires a
  second running process, which means either `docker-compose` (two
  containers) or an external database the operator must provision — both
  violate the simplest reading of the "build and run" contract as stated in
  the challenge.
- **In-memory storage (plain dicts, or pandas DataFrames held in the
  process)** — Fastest to build and avoids a database layer entirely.
  Rejected because data would not survive a process or container restart
  (unacceptable for something explicitly billed as "ingest once, query
  many times"), there is no SQL query surface for the enrichment joins
  described in §3.2 of the plan (they would have to be hand-written in
  Python), and it hides exactly the persistence design decisions the
  challenge is implicitly testing.

## Decision

Use **SQLite** as the storage engine, accessed through **SQLAlchemy 2.0's
typed ORM** (`Mapped[...]` / `mapped_column`) rather than raw SQL or
SQLAlchemy Core. The database file path is configurable via the
`FRESHFLOW_DB_PATH` environment variable so an operator can mount a volume
for persistence across container restarts; inside the container it defaults
to `/data/freshflow.db` (see the `Dockerfile`). Using the ORM rather than
hand-written SQL means the engine can be swapped to PostgreSQL later by
changing one connection URL and adjusting a small number of dialect-specific
details (e.g. `JSON` column behavior), without rewriting query code.

## Consequences

**Positive:**

- The run contract (`docker build && docker run`) holds with a single
  container and no external service dependency.
- ACID transactions give ingest its atomic replace-per-dataset guarantee
  (ADR-009) without extra application-level locking.
- The ORM's typed models (`app/models/`) are self-documenting and are
  checked by `mypy --strict`, catching column/type mismatches at review
  time rather than at runtime.
- A future migration to PostgreSQL is a configuration change, not a
  rewrite, because the ORM already abstracts the SQL dialect.

**Negative:**

- SQLite is not a true multi-writer database; a deployment with many
  concurrent ingest clients would need to move to PostgreSQL (or another
  client/server database) well before this design's limits were reached
  in read throughput.
- The database file's durability depends on the operator mounting a
  volume; without one, data is lost when the container is removed (this is
  documented in the README's run instructions, not hidden).
- SQLite's type affinity is looser than PostgreSQL's; care is required in
  the ORM layer (e.g. explicit `Numeric` columns for `Decimal` fields, see
  ADR-014) to avoid silently losing precision that a stricter database
  would have caught at write time.
