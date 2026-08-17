# ADR-012: Toolchain

Status: Accepted
Date: 2026-08-16

## Context

The project needs a Python dependency manager, a lint/format tool, a static
type checker and a test runner, all wired into CI as blocking gates
([PLAN.md](../PLAN.md) §6.1). The code was written in parallel workstreams
against contracts frozen up front, so consistent, automatically enforced
style and typing rules matter more than usual: there is no single author's
implicit conventions to fall back on, and the tooling has to do enforcement
work that a small co-located team might otherwise do by habit.

## Options Considered

- **uv + ruff (lint & format) + mypy --strict + pytest (chosen)** — `uv`
  resolves and locks dependencies quickly and reproducibly (`uv.lock`), and
  its `uv sync --frozen` install mode makes the Dockerfile's dependency
  layer both fast and byte-for-byte reproducible from the committed
  lockfile. `ruff` subsumes what used to take three or four separate tools:
  pycodestyle/pyflakes-equivalent linting, isort's import sorting, a
  formatter, and (with `pydocstyle` rules enabled) a docstring-convention
  checker, all in one fast Rust binary. It is configured here with
  `select = ["E","W","F","I","N","B","UP","SIM","C4","RUF","D"]` and
  Google-convention `pydocstyle`, enforcing the code-quality standard in
  PLAN.md §2.2 directly: typed functions, no mutable default arguments via
  `B006`/`B008`, docstring presence. `mypy --strict` on `app/` catches
  missing annotations, implicit `Any` and type mismatches. That matters
  specifically because this codebase mixes ORM models, Pydantic schemas and
  plain functions, and the seams between them — `Decimal` vs. `float` at
  the API boundary, ADR-014 — are exactly where type errors like to hide.
  `pytest` (+`pytest-cov`) is the standard test runner, with a
  `-m e2e`/`-m smoke` marker split so CI stages can run subsets
  independently.
- **pip/poetry** — pip alone has no native lockfile concept, so `pip-tools`
  or similar would have to be layered on. poetry has a lockfile and a
  mature ecosystem, but is slower at resolution and install than `uv` in
  practice, and adds configuration surface (its own build backend,
  `pyproject.toml` conventions) for no capability this project needs beyond
  what `uv` + `hatchling` already provide.
- **black + flake8 + isort** — The pre-`ruff` standard combination, each
  tool doing one job well, with functionally similar results for formatting
  and import sorting. Three tools means three configurations, three CI
  steps and three times the invocation overhead, for checks `ruff` already
  performs from a single config.
- **No static type checking** — Would simplify CI by one blocking job and
  remove friction for contributors unfamiliar with strict typing. Not
  seriously considered: PLAN.md §2.2 mandates full type annotations
  end-to-end, and in a codebase with several ORM/Pydantic/plain-function
  seams handling money (`Decimal`) and identifiers (`int` item numbers vs.
  their float-string CSV representations), the class of bugs static typing
  catches is exactly the class this project cannot afford to catch only at
  runtime.

## Decision

Use **uv** for dependency management and locking, **ruff** for both linting
and formatting (`ruff check`, `ruff format --check`), **mypy --strict** on
`app/`, and **pytest** + **pytest-cov** for testing, wired as blocking CI
jobs (`lint` → `typecheck` → `test` → `e2e` → `docker`, PLAN.md §6.1).
`hadolint` additionally lints the Dockerfile as part of the `docker` CI job.

## Consequences

One fast tool (`ruff`) replaces what would otherwise be three or four
separate lint/format/import-sort tools, which keeps both CI configuration
and the local developer commands down to a handful of `uv run` one-liners.
`uv.lock` gives fully reproducible installs locally and in the Docker
build, eliminating dependency drift between the parallel workstreams that
built this codebase. `mypy --strict` catches a whole class of boundary bugs
— implicit `Any`, missing annotations, `Decimal`/`float` confusion — before
they reach tests or review, which matters more than usual given the
contract-first process this project used.

Friction we accepted:

- `mypy --strict` is not free. Third-party libraries without complete type
  stubs, or code that genuinely needs a dynamic escape hatch, require
  explicit `# type: ignore[code]` annotations, themselves checked for
  staleness via `warn_unused_ignores`.
- `uv` is young relative to pip and poetry. Its ecosystem and community
  troubleshooting material are smaller, a minor onboarding cost for anyone
  unfamiliar with it.
- Enforcing `pydocstyle`-via-ruff (`D` rules) on every public function is
  discipline overhead during development: every route handler, service
  function and model needs a compliant Google-style docstring before
  `ruff check` passes, not merely before merge.
