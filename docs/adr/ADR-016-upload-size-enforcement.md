# ADR-016: Upload size enforcement

Status: Accepted
Date: 2026-08-16

## Context

`POST /api/v1/ingest/{dataset}` accepts an arbitrary multipart CSV upload.
Without a size limit, a single request (accidental or malicious) could
stream an unbounded amount of data into the process, exhausting memory or
disk before the ingest pipeline ever gets a chance to reject the file for a
content reason. The service needs a deliberate, enforced upper bound
(`settings.max_upload_bytes`, default 50,000,000 bytes,
`FRESHFLOW_MAX_UPLOAD_BYTES`-configurable via `app/config.py`) and a
decision about *how* that bound is enforced, since several plausible
approaches differ in trustworthiness and where the enforcement point lives.

## Options Considered

- **Stream the body in fixed-size chunks and abort once the running total
  exceeds `max_upload_bytes`, never trusting `Content-Length` (chosen)** —
  `app/ingest/router.py`'s `ingest_dataset_endpoint` reads the upload via
  `UploadFile.read(_UPLOAD_READ_CHUNK_BYTES)` in a loop (1 MB chunks),
  accumulating `total_bytes`. The moment `total_bytes > max_bytes`, the
  file handle is closed and a 413 `application/problem+json` response is
  returned immediately — before the service layer, the CSV parser, or the
  database ever see the file. Enforcement is based purely on bytes actually
  read off the wire, so it holds regardless of what (if anything) the
  client claimed about the upload's size.
- **Trust the `Content-Length` header** — Read the header, reject upfront
  if it exceeds the limit, then read the body without further checking.
  Simpler (one comparison, no chunked-read loop), but `Content-Length` is
  client-supplied and not authoritative: a client can send a small or
  absent `Content-Length` and then stream an arbitrarily large body (or one
  that doesn't match the declared length at all), which defeats the limit
  entirely for exactly the adversarial case the limit exists to stop.
  Rejected as trusting attacker-controlled input for a security-relevant
  decision.
- **Enforce the limit only at the server/proxy level (e.g. a reverse
  proxy's `client_max_body_size`, or a Uvicorn/ASGI-server-level cap)** —
  Pushes the concern outside the application entirely. This can be a
  reasonable *additional* layer in a production deployment, but as the
  *only* enforcement it couples correct behavior to how the service happens
  to be deployed: the take-home deliverable is `docker build && docker run`
  with no reverse proxy in front of it (ADR-002), so a proxy-level limit
  would never actually apply in the shipped configuration, and the limit
  would silently stop existing for anyone who runs the container directly.
  Rejected as out of the application's control and untested by this
  codebase's own test suite.
- **No limit** — Accept uploads of any size. Simplest, but leaves an
  unbounded-memory/unbounded-disk denial-of-service vector on the one
  endpoint in the service that accepts arbitrary client-supplied bytes;
  rejected outright as a known, cheaply-avoidable risk for a service whose
  entire job is accepting file uploads.

## Decision

Enforce `settings.max_upload_bytes` by streaming the multipart file body in
`_UPLOAD_READ_CHUNK_BYTES` (1 MB) chunks inside
`ingest_dataset_endpoint`, summing bytes actually read, and returning a 413
`application/problem+json` response (`ProblemDetail`, ADR-011) the instant
the running total exceeds the limit — closing the upload file handle first
so the connection doesn't keep streaming data the service has already
decided to reject. `Content-Length` is never consulted for this decision:
enforcement is based solely on observed bytes. This lives in the router
(`app/ingest/router.py`), not the service layer, because it is purely an
HTTP/transport concern — by the time `service.ingest_dataset` is called, the
file is already known to be within bounds.

## Consequences

**Positive:**

- The limit holds regardless of what the client claims: a spoofed, absent,
  or wrong `Content-Length` cannot bypass it, because the decision is made
  from bytes actually read.
- Enforcement works identically however the container is deployed —
  directly exposed, behind a reverse proxy, behind a load balancer — since
  it does not depend on any component outside the application process.
  Additional server/proxy-level limits remain a reasonable defense-in-depth
  layer in a real deployment, but the application no longer depends on one
  existing.
- Memory use while checking the limit is bounded to one chunk (1 MB) of
  over-limit data at most, not the full oversized body, since the read loop
  aborts as soon as the running total crosses the threshold rather than
  buffering the entire upload first and checking afterward.
- The rejection is a standard RFC 9457 problem response (ADR-011), so an
  oversized upload is reported the same way every other domain error is,
  not as a raw connection reset or an opaque framework error.

**Negative:**

- Reading the body in a chunked loop in the router is a few more lines than
  a single `Content-Length` comparison, and is the one piece of
  upload-handling logic that lives in the router rather than the service
  layer (documented in `app/ingest/router.py`'s module docstring as a
  deliberate exception to "routers are thin", alongside the 404
  `IngestNotFoundError` handling).
- A client sending exactly the limit's worth of bytes very slowly still
  occupies a connection for the duration of the (rejected) upload, since
  the limit is only checked as bytes arrive, not upfront — a slow-loris-style
  concern this ADR does not address and considers out of scope for the
  container-only, no-reverse-proxy deployment target (ADR-002).
