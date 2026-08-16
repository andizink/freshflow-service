# ADR-011: Error response format

Status: Accepted
Date: 2026-08-16

## Context

The API needs a consistent, machine-parseable shape for error responses
(unknown store, bad CSV header, unexpected server error, and so on) so API
consumers can handle failures uniformly rather than parsing ad hoc,
per-endpoint error bodies. FastAPI's own default validation-error shape
(`{"detail": ...}`) covers request/query/path parameter validation
automatically, but the service also raises its own domain errors
(`StoreNotFoundError`, `HeaderError`) that need a defined, documented
response body.

## Options Considered

- **RFC 9457 `application/problem+json` (chosen)** — A standardized,
  IETF-specified shape (`type`, `title`, `status`, `detail`, plus optional
  extension members) for HTTP API error bodies. Adopting a standard rather
  than inventing a bespoke shape means any HTTP client or tooling already
  familiar with problem+json needs no FreshFlow-specific documentation to
  parse errors, and the shape is self-describing (a `title` and `detail`
  distinguish the general problem class from the specific occurrence).
  FastAPI's built-in 422 validation-error body
  (`{"detail": [...]}`) is deliberately left as-is for request/parameter
  validation errors, since rewriting FastAPI's own validation-error
  pipeline to match RFC 9457 exactly would be a large amount of machinery
  for a body shape that is already well-documented and auto-generated in
  the OpenAPI schema; every other error path (404, 400, 500) uses RFC
  9457 problem+json via custom exception handlers.
- **Ad hoc `{"error": "..."}` bodies** — The simplest possible shape to
  write, but non-standard: every consumer has to learn this specific
  service's error format from scratch, there's no room for structured
  metadata (status, type, distinguishing one error class from another)
  without inventing more bespoke fields, and it doesn't compose with any
  existing tooling that already understands a standard error format.
- **FastAPI default `{"detail": "..."}` for everything** — Consistent with
  what FastAPI does automatically for validation errors, and requires the
  least custom code. Rejected as the *only* error shape because
  `{"detail": ...}` alone carries no `status`, `title`, or `type`
  discriminator — a consumer parsing only `detail` cannot reliably
  distinguish a 404 from a 400 from a 500 without also inspecting the raw
  HTTP status code out-of-band, and it isn't backed by any published
  standard the way RFC 9457 is.

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

**Positive:**

- Non-validation error responses have a single, standardized, documented
  shape across every endpoint (`type`, `title`, `status`, `detail`),
  reducing the amount of FreshFlow-specific error-handling knowledge an
  API consumer needs.
- Domain errors (`StoreNotFoundError`, `HeaderError`) map cleanly onto
  HTTP status codes via dedicated exception handlers, keeping that mapping
  in one place (`app/main.py`) rather than scattered through route
  handlers.
- Because it's a real content type (`application/problem+json`), HTTP
  tooling and clients that already understand the standard need no
  FreshFlow-specific documentation to interpret an error.

**Negative:**

- The API now has two distinct error body shapes in practice — RFC 9457
  problem+json for domain/server errors, and FastAPI's own
  `{"detail": [...]}` for 422 request-validation errors — which consumers
  must be aware of rather than assuming one uniform shape everywhere.
- Adopting RFC 9457 fully (rather than the lighter `{"detail": ...}`
  default) is marginally more code: a shared `ProblemDetail` model and a
  small set of exception handlers, versus none.
