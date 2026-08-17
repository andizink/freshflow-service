# ADR-016: Upload size enforcement

Status: Accepted
Date: 2026-08-16

## Context

`POST /api/v1/ingest/{dataset}` accepts an arbitrary multipart CSV upload.
Without a size limit, one request — accidental or malicious — could stream
an unbounded amount of data into the process, exhausting memory or disk
before the ingest pipeline ever gets to reject the file for a content
reason. The service needs an enforced upper bound
(`settings.max_upload_bytes`, default 50,000,000 bytes, configurable via
`FRESHFLOW_MAX_UPLOAD_BYTES` in `app/config.py`) and a decision about *how*
that bound is enforced, since the plausible approaches differ in
trustworthiness and in where the enforcement point lives.

## Options Considered

- **Stream the body in fixed-size chunks and abort once the running total
  exceeds `max_upload_bytes`, never trusting `Content-Length` (chosen)** —
  `app/ingest/router.py`'s `ingest_dataset_endpoint` reads the upload via
  `UploadFile.read(_UPLOAD_READ_CHUNK_BYTES)` in a loop (1 MB chunks),
  accumulating `total_bytes`. The moment `total_bytes > max_bytes`, the
  file handle is closed and a 413 `application/problem+json` response goes
  back immediately, before the service layer, the CSV parser or the
  database ever see the file. Enforcement rests purely on bytes actually
  read off the wire, so it holds regardless of what the client claimed
  about the upload's size.
- **Trust the `Content-Length` header** — Read the header, reject upfront
  if it exceeds the limit, then read the body without further checking.
  Simpler, but `Content-Length` is client-supplied and not authoritative. A
  client can send a small or absent `Content-Length` and then stream an
  arbitrarily large body, which defeats the limit for exactly the
  adversarial case it exists to stop. Rejected as trusting
  attacker-controlled input for a security-relevant decision.
- **Enforce the limit only at the server/proxy level** (a reverse proxy's
  `client_max_body_size`, or a Uvicorn/ASGI-level cap) — Pushes the concern
  outside the application. Reasonable as an *additional* layer in a
  production deployment, but as the *only* enforcement it couples correct
  behavior to how the service happens to be deployed. The deliverable here
  is `docker build && docker run` with no reverse proxy in front of it
  (ADR-002), so a proxy-level limit would never apply in the shipped
  configuration, and the limit would silently stop existing for anyone
  running the container directly. It is also untestable by this codebase's
  own suite.
- **No limit** — Simplest, and leaves an unbounded-memory/unbounded-disk
  denial-of-service vector on the one endpoint that accepts arbitrary
  client-supplied bytes. Rejected outright as a known, cheaply avoidable
  risk for a service whose entire job is accepting file uploads.

## Decision

Enforce `settings.max_upload_bytes` by streaming the multipart file body in
`_UPLOAD_READ_CHUNK_BYTES` (1 MB) chunks inside `ingest_dataset_endpoint`,
summing bytes actually read, and returning a 413
`application/problem+json` response (`ProblemDetail`, ADR-011) the instant
the running total exceeds the limit, closing the upload file handle first
so the connection doesn't keep streaming data the service has already
decided to reject. `Content-Length` is never consulted; enforcement is
based solely on observed bytes. This lives in the router
(`app/ingest/router.py`) rather than the service layer because it is purely
an HTTP/transport concern. By the time `service.ingest_dataset` is called,
the file is already known to be within bounds.

## Consequences

The limit holds regardless of what the client claims: a spoofed, absent or
wrong `Content-Length` cannot bypass it. It also works identically however
the container is deployed — directly exposed, behind a reverse proxy,
behind a load balancer — since it depends on nothing outside the
application process. Server- or proxy-level limits remain a sensible
defense-in-depth layer, but the application no longer depends on one
existing. Memory use while checking is bounded to a single 1 MB chunk of
over-limit data, because the loop aborts as soon as the running total
crosses the threshold rather than buffering the whole upload first. The
rejection is a standard RFC 9457 problem response (ADR-011), so an
oversized upload is reported like every other domain error rather than as a
raw connection reset.

Two downsides:

- The chunked read loop is a few more lines than a single `Content-Length`
  comparison, and it is the one piece of upload handling that lives in the
  router rather than the service layer. `app/ingest/router.py`'s module
  docstring records it as a deliberate exception to "routers are thin",
  alongside the 404 `IngestNotFoundError` handling.
- A client sending exactly the limit's worth of bytes very slowly still
  occupies a connection for the duration of the rejected upload, since the
  limit is only checked as bytes arrive. This slow-loris-style concern is
  out of scope for the container-only, no-reverse-proxy deployment target
  (ADR-002).
