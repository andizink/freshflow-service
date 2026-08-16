# ADR-001: Web framework

Status: Accepted
Date: 2026-08-16

## Context

FreshFlow needs a small, well-documented HTTP API with two core endpoints (CSV
ingest, recommendations query), plus supporting endpoints for audit and
health. The challenge brief emphasizes both correctness and the quality of
the delivered artifact — reviewers will read the code and exercise the API
directly, and part of the deliverable is documentation. The framework choice
should minimize boilerplate for request/response validation (the data is
dirty; we want strong typing at the API boundary too) and should not require
infrastructure beyond a single container.

## Options Considered

- **FastAPI** — Pydantic v2 models give request and response validation "for
  free," including automatic coercion errors that map cleanly onto our own
  422 semantics. OpenAPI/Swagger documentation is generated automatically
  from the same type hints used for validation, which directly doubles as
  part of the documentation deliverable required by the challenge. It is
  async-capable (useful for streaming file uploads without blocking the
  event loop) and is the de facto standard for new Python HTTP APIs as of
  2026, so any reviewer will find the code idiomatic. The cost is a small
  amount of extra machinery (dependency injection, Pydantic model
  boilerplate) relative to a minimal framework, which is a poor trade only
  for a genuinely trivial service — this one is not.
- **Flask** — Minimal and universally known, with a huge ecosystem. But it
  gives none of FastAPI's validation or documentation generation for free;
  we would have to hand-write request parsing, response schemas, and an
  OpenAPI document, which is exactly the kind of undifferentiated work this
  project cannot afford to spend on. Flask is also synchronous by default,
  which is a worse fit for streaming CSV uploads. For a green-field service
  in 2026 it also reads as a dated choice to reviewers.
- **Django + Django REST Framework** — Batteries-included (admin UI, ORM,
  auth, migrations), which is valuable for large, long-lived applications
  with many resources and multiple developer teams. For a two-endpoint
  service this is substantial overkill: slow to scaffold, heavier runtime
  footprint, and most of its batteries (admin UI, auth, sessions) are
  entirely unused here.

## Decision

Use **FastAPI** with **Uvicorn** as the ASGI server. Pydantic v2 models
(`app/schemas/`) define both the ingest report and recommendation response
shapes; FastAPI validates path/query parameters (e.g. the `day` query
parameter as an ISO date, `dataset` as a `StrEnum`) automatically, producing
422 responses for malformed input without custom code. The auto-generated
`/docs` and `/openapi.json` endpoints are treated as part of the
documentation deliverable alongside the hand-written docs in `docs/`.

## Consequences

**Positive:**

- Request/response validation, coercion, and error messages come from the
  framework, not hand-written code — fewer places for the ingest/query
  boundary to silently disagree with its documented contract.
- `/docs` and `/openapi.json` are always in sync with the code, because they
  are generated from the same Pydantic models the handlers use.
- Type hints on route handlers double as documentation and as input to
  `mypy --strict`, reinforcing the project's typed-codebase standard
  (PLAN.md §2.2).
- Async support means a large CSV upload does not block other requests
  (e.g. a concurrent `/health` probe) while it streams.

**Negative:**

- Slightly more moving parts than Flask for what is, functionally, a small
  service: dependency injection (`Depends`), Pydantic model classes, and
  FastAPI's own request/response lifecycle have to be understood by anyone
  touching the router layer.
- FastAPI's automatic 422 handling for path/query parameters is separate
  from this project's own RFC 9457 problem+json error shape (ADR-011) for
  everything else, so the two error paths must be reconciled explicitly
  rather than assumed to be uniform.
