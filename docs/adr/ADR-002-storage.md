# ADR-002: Storage

Status: Accepted
Date: 2026-08-16

## Context

The service must persist four ingested datasets (~76,000 rows total),
ingest reports and quarantined rows, and serve queries against them. The
run contract is strict: `docker build` followed by `docker run` must be
sufficient. No `docker-compose`, no external services to provision, no
manual setup steps.

Tens of thousands of rows is well within what a single-file embedded
database handles comfortably, and the service does not need concurrent
multi-writer throughput. Ingest is an infrequent, replace-per-dataset
operation (ADR-009) and recommendation queries are simple reads.

## Options Considered

- **SQLite via SQLAlchemy 2.0** — Zero external dependencies: the database
  is a file inside the container, optionally on a mounted volume, so the
  "one container, `docker build && docker run`" contract holds trivially.
  SQLite is ACID and more than capable of this service's read/write
  patterns at ~75k rows. Its well-known limitation is that it is not a true
  multi-writer database; concurrent write throughput does not scale the way
  a client/server database's does. That is an acceptable trade for this
  workload (occasional bulk replace, frequent light reads), though not at
  real production scale with many concurrent ingest clients.
- **PostgreSQL** — The production-realistic choice, and what this service
  would likely migrate to if FreshFlow's data volume grew by orders of
  magnitude. It requires a second running process, which means either
  `docker-compose` or an external database the operator must provision.
  Both violate the simplest reading of the build-and-run contract.
- **In-memory storage (plain dicts, or pandas DataFrames held in the
  process)** — Fastest to build, no database layer at all. Rejected on
  three counts: data would not survive a restart, which is unacceptable for
  something billed as "ingest once, query many times"; there is no SQL
  query surface for the enrichment joins described in §3.2 of the plan, so
  they would be hand-written in Python; and it sidesteps exactly the
  persistence decisions the challenge is implicitly testing.

## Decision

Use **SQLite** as the storage engine, accessed through **SQLAlchemy 2.0's
typed ORM** (`Mapped[...]` / `mapped_column`) rather than raw SQL or
SQLAlchemy Core. The database file path is configurable via the
`FRESHFLOW_DB_PATH` environment variable so an operator can mount a volume
for persistence across container restarts; inside the container it defaults
to `/data/freshflow.db` (see the `Dockerfile`). Using the ORM rather than
hand-written SQL means the engine can be swapped to PostgreSQL later by
changing one connection URL and adjusting a small number of dialect
specifics (e.g. `JSON` column behavior), without rewriting query code.

## Consequences

The run contract holds with a single container and no external service.
ACID transactions give ingest its atomic replace-per-dataset guarantee
(ADR-009) without application-level locking, and the typed ORM models in
`app/models/` are self-documenting and checked by `mypy --strict`, so
column/type mismatches surface at review time rather than at runtime. A
future migration to PostgreSQL is a configuration change rather than a
rewrite.

What we accept in exchange:

- SQLite is not a true multi-writer database. A deployment with many
  concurrent ingest clients would need PostgreSQL (or another
  client/server database) well before read throughput became the limit.
- Durability depends on the operator mounting a volume. Without one, data
  is lost when the container is removed. This is documented in the
  README's run instructions rather than hidden.
- SQLite's type affinity is looser than PostgreSQL's, so the ORM layer has
  to be careful — explicit `Numeric` columns for `Decimal` fields, see
  ADR-014 — to avoid silently losing precision a stricter database would
  have caught at write time.
