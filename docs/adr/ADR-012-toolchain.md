# ADR-012: Toolchain

Status: Accepted
Date: 2026-08-16

## Context

The project needs a Python dependency manager, a lint/format tool, a static
type checker, and a test runner, all wired into CI as blocking gates
(PLAN.md §6.1). Because the code is being written in parallel by multiple
agents against frozen contracts, consistent, automatically-enforced style
and typing rules matter more than usual — there is no single author's
implicit conventions to fall back on, so the tooling has to do the
enforcement work that a small, single-author team might otherwise do by
habit.

## Options Considered

- **uv + ruff (lint & format) + mypy --strict + pytest (chosen)** — `uv`
  resolves and locks dependencies quickly and reproducibly
  (`uv.lock`), and its `uv sync --frozen` install mode makes the
  Dockerfile's dependency layer both fast and byte-for-byte reproducible
  from the committed lockfile. `ruff` subsumes what used to require three
  or four separate tools (pycodestyle/pyflakes-equivalent linting, isort's
  import sorting, a formatter, and — with `pydocstyle` rules enabled — a
  docstring-convention checker), running as a single fast Rust binary. It
  is configured here with `select = ["E","W","F","I","N","B","UP","SIM",
  "C4","RUF","D"]` and Google-convention `pydocstyle`, directly enforcing
  the code-quality standard in PLAN.md §2.2 (typed functions, no mutable
  default arguments via `B006`/`B008`, docstring presence). `mypy --strict`
  on `app/` catches missing annotations, implicit `Any`, and type
  mismatches — valuable specifically because this codebase mixes ORM
  models, Pydantic schemas, and plain functions, and the seams between
  them (e.g. `Decimal` vs. `float` at the API boundary, ADR-014) are
  exactly where type errors like to hide. `pytest` (+`pytest-cov`) is the
  standard Python test runner, with a `-m e2e`/`-m smoke` marker split so
  CI stages can run subsets independently.
- **pip/poetry** — pip alone has no native lockfile concept (`pip-tools` or
  similar would need to be layered on); poetry has a lockfile and a mature
  ecosystem, but is slower at dependency resolution and install than `uv`
  in practice, and adds more configuration surface (its own build backend,
  `pyproject.toml` conventions) for no capability this project actually
  needs beyond what `uv` + `hatchling` already provide.
- **black + flake8 + isort** — The pre-`ruff` standard combination, each
  tool doing one job well. Functionally similar end results to `ruff` for
  formatting and import sorting, but three separate tools means three
  separate configurations, three separate CI steps, and three times the
  invocation overhead — `ruff` performs the same checks (and more, via its
  larger rule catalog) as a single, faster, single-configuration tool.
- **No static type checking** — Would simplify CI (one less blocking job)
  and remove friction for contributors unfamiliar with strict typing. Not
  seriously considered: PLAN.md §2.2 mandates full type annotations
  end-to-end as a code-quality standard, and in a codebase with several
  ORM/Pydantic/plain-function seams handling money (`Decimal`) and
  identifiers (`int` item numbers vs. their float-string CSV
  representations), the class of bugs static typing catches is exactly the
  class this project cannot afford to catch only at runtime or not at all.

## Decision

Use **uv** for dependency management and locking, **ruff** for both
linting and formatting (`ruff check`, `ruff format --check`), **mypy
--strict** on `app/`, and **pytest** + **pytest-cov** for testing, wired as
blocking CI jobs (`lint` → `typecheck` → `test` → `e2e` → `docker`, PLAN.md
§6.1). `hadolint` additionally lints the Dockerfile as part of the `docker`
CI job.

## Consequences

**Positive:**

- A single fast tool (`ruff`) replaces what would otherwise be three or
  four separate lint/format/import-sort tools, simplifying CI
  configuration and local developer commands to a small number of `uv
  run` one-liners.
- `uv.lock` gives fully reproducible installs both locally and in the
  Docker build, eliminating "works on my machine" dependency drift across
  the parallel agent lanes that built this codebase.
- `mypy --strict` catches an entire class of boundary bugs (implicit
  `Any`, missing annotations, `Decimal`/`float` confusion) before they
  reach tests or review, which matters more than usual given the
  multi-agent, contract-first development process this project used.

**Negative:**

- `mypy --strict` has real friction cost: third-party libraries without
  complete type stubs, or code that genuinely needs a dynamic escape
  hatch, require explicit `# type: ignore[code]` annotations (themselves
  checked for staleness via `warn_unused_ignores`) rather than being
  silently permitted.
- `uv` is a comparatively young tool relative to pip/poetry; its ecosystem
  and community troubleshooting resources are smaller, which is a minor
  onboarding cost for contributors unfamiliar with it.
- Enforcing `pydocstyle`-via-ruff (`D` rules) on every public function is
  additional discipline overhead during development — every route
  handler, service function, and model needs a compliant Google-style
  docstring before `ruff check` passes, not just before merge.
