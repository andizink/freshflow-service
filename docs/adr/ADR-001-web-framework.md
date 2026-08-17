# ADR-001: Web framework

Status: Accepted
Date: 2026-08-16

## Context

FreshFlow needs a small, well-documented HTTP API with two core endpoints
(CSV ingest, recommendations query) plus supporting endpoints for audit and
health. The challenge brief emphasizes correctness and the quality of the
delivered artifact: reviewers will read the code and exercise the API
directly, and part of the deliverable is documentation. The framework
should minimize boilerplate for request/response validation — the data is
dirty, so we want strong typing at the API boundary too — and must not
require infrastructure beyond a single container.

## Options Considered

- **FastAPI** — Pydantic v2 models give request and response validation for
  free, including coercion errors that map cleanly onto our own 422
  semantics. OpenAPI/Swagger documentation is generated from the same type
  hints used for validation, so it doubles as part of the documentation
  deliverable. It is async-capable, useful for streaming file uploads
  without blocking the event loop, and it is the de facto standard for new
  Python HTTP APIs as of 2026, so any reviewer will find the code idiomatic.
  The cost is a little extra machinery (dependency injection, Pydantic model
  boilerplate) relative to a minimal framework. That is a poor trade only
  for a trivial service, and this one isn't.
- **Flask** — Minimal, universally known, huge ecosystem. But it gives none
  of FastAPI's validation or documentation generation for free: we would
  hand-write request parsing, response schemas and an OpenAPI document,
  which is exactly the undifferentiated work this project cannot afford.
  Flask is also synchronous by default, a worse fit for streaming CSV
  uploads.
- **Django + Django REST Framework** — Batteries included (admin UI, ORM,
  auth, migrations), which pays off in large, long-lived applications. For
  a two-endpoint service it is overkill: slow to scaffold, heavier runtime
  footprint, and most of the batteries go unused.

## Decision

Use **FastAPI** with **Uvicorn** as the ASGI server. Pydantic v2 models
(`app/schemas/`) define both the ingest report and recommendation response
shapes. FastAPI validates path and query parameters automatically (the
`day` query parameter as an ISO date, `dataset` as a `StrEnum`), producing
422 responses for malformed input without custom code. The auto-generated
`/docs` and `/openapi.json` endpoints count as part of the documentation
deliverable alongside the hand-written docs in `docs/`.

## Consequences

Validation, coercion and error messages come from the framework rather than
hand-written code, so there are fewer places for the ingest/query boundary
to silently disagree with its documented contract. `/docs` and
`/openapi.json` stay in sync with the code because they are generated from
the same Pydantic models the handlers use, and the type hints on route
handlers double as input to `mypy --strict`, reinforcing the project's
typed-codebase standard ([PLAN.md](../PLAN.md) §2.2). Async support means a
large CSV upload does not block a concurrent `/health` probe while it
streams.

The costs are modest but real:

- More moving parts than Flask for a functionally small service.
  Dependency injection (`Depends`), Pydantic model classes and FastAPI's
  request/response lifecycle all have to be understood by anyone touching
  the router layer.
- FastAPI's automatic 422 handling for path/query parameters is separate
  from this project's RFC 9457 problem+json error shape (ADR-011) used
  everywhere else, so the two error paths have to be reconciled explicitly
  rather than assumed uniform.
