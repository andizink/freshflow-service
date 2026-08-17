# ADR-011: Error response format

Status: Accepted
Date: 2026-08-16

## Context

The API needs a consistent, machine-parseable shape for error responses —
unknown store, bad CSV header, unexpected server error — so consumers can
handle failures uniformly instead of parsing ad hoc, per-endpoint bodies.
FastAPI's own default validation-error shape (`{"detail": ...}`) covers
request, query and path parameter validation automatically, but the service
also raises its own domain errors (`StoreNotFoundError`, `HeaderError`)
that need a defined, documented response body.

## Options Considered

- **RFC 9457 `application/problem+json` (chosen)** — A standardized,
  IETF-specified shape (`type`, `title`, `status`, `detail`, plus optional
  extension members) for HTTP API error bodies. Adopting a standard rather
  than inventing a bespoke shape means any client or tooling already
  familiar with problem+json needs no FreshFlow-specific documentation, and
  the shape is self-describing: `title` and `detail` separate the general
  problem class from the specific occurrence. FastAPI's built-in 422
  validation body (`{"detail": [...]}`) is left as-is for
  request/parameter validation, since rewriting FastAPI's own
  validation-error pipeline to match RFC 9457 would be a lot of machinery
  for a body shape that is already well documented and auto-generated in
  the OpenAPI schema. Every other error path (404, 400, 500) uses RFC 9457.
- **Ad hoc `{"error": "..."}` bodies** — The simplest thing to write, but
  non-standard. Every consumer learns this specific service's format from
  scratch, there's no room for structured metadata without inventing more
  bespoke fields, and it composes with no existing tooling.
- **FastAPI default `{"detail": "..."}` for everything** — Consistent with
  what FastAPI already does for validation errors and requires the least
  custom code. Rejected as the *only* error shape because `{"detail": ...}`
  carries no `status`, `title` or `type` discriminator: a consumer parsing
  only `detail` cannot reliably tell a 404 from a 400 from a 500 without
  inspecting the raw HTTP status code out-of-band, and it isn't backed by a
  published standard.

## Decision

Non-validation errors (unknown store → 404, bad CSV header → 400,
unhandled exceptions → 500) are mapped to RFC 9457
`application/problem+json` bodies (`app.schemas.errors.ProblemDetail`) via
FastAPI exception handlers registered in `app.main.create_app`. FastAPI's
default request-validation error body (422, `{"detail": [...]}`) is kept
as-is for path/query/body validation failures, since that is FastAPI's own
well-documented mechanism and reimplementing it would add complexity
without a clear benefit.

## Consequences

Non-validation errors now have a single, standardized, documented shape
across every endpoint, which cuts down how much FreshFlow-specific
error-handling knowledge a consumer needs. Domain errors
(`StoreNotFoundError`, `HeaderError`) map onto HTTP status codes through
dedicated exception handlers, so that mapping lives in one place
(`app/main.py`) rather than scattered through route handlers. And because
`application/problem+json` is a real content type, tooling that already
understands the standard needs no extra documentation from us.

The obvious wart is that the API has two error body shapes in practice: RFC
9457 for domain and server errors, FastAPI's `{"detail": [...]}` for 422
request-validation errors. Consumers have to be aware of that rather than
assuming one uniform shape. Adopting RFC 9457 is also marginally more code
than the default — a shared `ProblemDetail` model and a small set of
exception handlers, versus none.
