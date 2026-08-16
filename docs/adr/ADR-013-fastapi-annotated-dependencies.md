# ADR-013: FastAPI Annotated dependencies

Status: Accepted
Date: 2026-08-16

## Context

Every request handler that touches the database needs a request-scoped
SQLAlchemy `Session`, provided via FastAPI's dependency-injection system.
FastAPI historically supported (and its documentation and most tutorials
still show) declaring this as a call-in-default-value:
`def handler(session: Session = Depends(get_session))`. This project's
mandated ruff rule set (PLAN.md §2.2, §6.1) includes `bugbear` (`B`), and
`B008` specifically flags "do not perform function calls in argument
defaults" — which a literal `Depends(get_session)` default value is. The
project needs one consistent, lint-clean way to declare dependency-injected
parameters across every router.

## Options Considered

- **`Annotated[Session, Depends(get_session)]` style (chosen)** — Define a
  module-level type alias, `SessionDep = Annotated[Session,
  Depends(get_session)]` (in `app/db.py`), and use it as an ordinary type
  annotation on handler parameters: `def handler(session: SessionDep)`.
  This is FastAPI's own current recommended style (introduced alongside
  Python's `Annotated` support and promoted in FastAPI's docs as the
  preferred pattern since it decouples "what type is this" from "how is it
  resolved," and lets the same dependency alias be reused verbatim across
  every router without re-typing `Depends(...)`). It also happens to route
  around `B008` entirely, because the `Depends(...)` call sits inside a
  type alias's definition (evaluated once, at import time) rather than in
  a function's default-argument position (which is what `B008` actually
  flags — a call re-evaluated, at least in principle, on every
  definition).
- **Disable `B008` per-file for route modules** — Keep the traditional
  `Depends(...)` default-argument style everywhere and silence the linter
  for the routers via `per-file-ignores`. This preserves the (arguably)
  more immediately readable "the default value shows you what's injected"
  style some FastAPI tutorials use, but it means carving an exception into
  the project's otherwise-uniform lint configuration specifically to permit
  a pattern the tool is correctly identifying as fragile in the general
  case (a call in a default value is evaluated once at function
  *definition* time, which is easy to reason about only because FastAPI
  specifically treats `Depends` specially — the rule doesn't know that,
  and a per-file ignore doesn't communicate why it's safe here either).
- **Plain default-argument style, rule violation accepted** — Keep
  `Depends(...)` as a default value and simply accept the `B008` finding as
  a permanent, unresolved lint warning. Rejected outright: PLAN.md §2.2
  states lint cleanliness is a CI-blocking gate with no carve-outs — "code
  that isn't clean doesn't merge, regardless of which agent wrote it." An
  unresolved lint finding is not a viable end state under that policy.

## Decision

Every FastAPI dependency is declared once as an `Annotated[...]` type alias
next to its provider function — e.g. `SessionDep = Annotated[Session,
Depends(get_session)]` in `app/db.py` — and route handlers take it as a
plain, un-defaulted parameter: `session: SessionDep`. No route handler in
this codebase declares `Depends(...)` directly as a parameter default.

## Consequences

**Positive:**

- `ruff check` passes cleanly with the project's standard rule set
  (including `B008`) without any per-file or per-line exceptions —
  consistent with the "no carve-outs" lint policy.
- Matches FastAPI's own current documentation and recommended style, so
  the code reads as idiomatic to anyone familiar with modern FastAPI, not
  as a project-specific workaround.
- Dependency aliases (`SessionDep`) are defined once and reused verbatim
  across every router (`app/ingest/router.py`, `app/recommendations/router.py`,
  `app/stores/router.py`), so a future change to how sessions are
  provided (e.g. adding a retry policy) touches one definition, not every
  handler signature.

**Negative:**

- Contributors who learned FastAPI from older tutorials or examples using
  `Depends(...)` as a default value have to learn the `Annotated` idiom
  specifically for this codebase, which is a small onboarding cost.
- The indirection (a type alias defined elsewhere, rather than the
  dependency being visibly spelled out at the call site) makes a handler
  signature very slightly less self-contained — a reader has to know to
  look at `SessionDep`'s definition in `app/db.py` to see exactly which
  provider function is wired in, rather than seeing `Depends(get_session)`
  inline.
