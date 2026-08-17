# ADR-013: FastAPI Annotated dependencies

Status: Accepted
Date: 2026-08-16

## Context

Every request handler that touches the database needs a request-scoped
SQLAlchemy `Session`, provided via FastAPI's dependency-injection system.
FastAPI historically supported — and its documentation and most tutorials
still show — declaring this as a call in a default value:
`def handler(session: Session = Depends(get_session))`. This project's
mandated ruff rule set ([PLAN.md](../PLAN.md) §2.2, §6.1) includes
`bugbear` (`B`), and `B008` flags "do not perform function calls in
argument defaults", which is exactly what a literal `Depends(get_session)`
default is. We need one consistent, lint-clean way to declare
dependency-injected parameters across every router.

## Options Considered

- **`Annotated[Session, Depends(get_session)]` style (chosen)** — Define a
  module-level type alias, `SessionDep = Annotated[Session,
  Depends(get_session)]` in `app/db.py`, and use it as an ordinary type
  annotation: `def handler(session: SessionDep)`. This is FastAPI's own
  current recommended style, promoted in its docs because it decouples
  "what type is this" from "how is it resolved" and lets the same alias be
  reused verbatim across every router. It also routes around `B008`
  entirely, because the `Depends(...)` call sits inside a type alias
  definition, evaluated once at import time, rather than in a function's
  default-argument position.
- **Disable `B008` per-file for route modules** — Keep the traditional
  default-argument style and silence the linter for the routers via
  `per-file-ignores`. This preserves the arguably more readable "the
  default value shows you what's injected" style, but it carves an
  exception into an otherwise-uniform lint configuration to permit a
  pattern the tool is correctly identifying as fragile in the general case.
  A per-file ignore also doesn't communicate *why* the pattern is safe here
  (FastAPI treats `Depends` specially; the rule doesn't know that).
- **Plain default-argument style, rule violation accepted** — Keep
  `Depends(...)` as a default and live with a permanent `B008` finding.
  Rejected outright: PLAN.md §2.2 makes lint cleanliness a CI-blocking gate
  with no carve-outs — "code that isn't clean doesn't merge, whoever wrote
  it." An unresolved lint finding is not a viable end state under that
  policy.

## Decision

Every FastAPI dependency is declared once as an `Annotated[...]` type alias
next to its provider function — e.g. `SessionDep = Annotated[Session,
Depends(get_session)]` in `app/db.py` — and route handlers take it as a
plain, un-defaulted parameter: `session: SessionDep`. No route handler in
this codebase declares `Depends(...)` directly as a parameter default.

## Consequences

`ruff check` passes cleanly with the project's standard rule set, `B008`
included, without per-file or per-line exceptions, which is consistent with
the no-carve-outs lint policy. The code also matches FastAPI's current
documentation, so it reads as idiomatic modern FastAPI rather than a
project-specific workaround. Defining each dependency alias once and
reusing it across `app/ingest/router.py`,
`app/recommendations/router.py` and `app/stores/router.py` means a future
change to how sessions are provided (adding a retry policy, say) touches
one definition instead of every handler signature.

Two small costs: contributors who learned FastAPI from older tutorials have
to pick up the `Annotated` idiom, and the indirection makes a handler
signature slightly less self-contained, since a reader has to look at
`SessionDep` in `app/db.py` to see which provider function is wired in
rather than reading `Depends(get_session)` inline.
