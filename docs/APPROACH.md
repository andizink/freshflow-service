# How this solution was built

I want to be upfront about the method before anything else: I built this
solution by directing a team of AI coding agents. The problem analysis,
the architecture decisions, the quality bar, the review process and the
final sign-off are mine; large parts of the code and prose were produced
by agents working to my specification, in parallel, and then reviewed —
by another agent I pointed at the result adversarially, and by me.

I'm sharing this document because I think *how* the work was directed is
at least as relevant to a CTO conversation as the code itself. Below is
what I actually did, in order, including the parts where my first
assumptions turned out to be wrong.

## 1. I profiled the data before designing anything

The task description is two endpoints and a Dockerfile. That's not a
CTO case. So before choosing a framework I ran a profiling pass over all
four CSVs (~76,000 rows), and that changed everything: the files are
systematically dirty. Eight spellings of the same store id. Item numbers
as floats. Two date formats in one column. Negative order quantities.
Items that don't exist in the catalog. Duplicates. Fractional "pieces".

My read: the data is the actual test. A submission that pipes CSVs into
a database either crashes on these rows or silently serves wrong
answers, and both failure modes tell a hiring team what they need to
know. So the core design principle came before any code:

> Repair what has exactly one reasonable interpretation. Quarantine what
> doesn't — never guess. Report everything, and keep the rejected rows
> retrievable for audit.

Everything else in the repo is that sentence applied case by case. The
full defect catalog and the reasoning per defect is in
[DATA_GUIDE.md](DATA_GUIDE.md) and [DATA_QUALITY.md](DATA_QUALITY.md).

## 2. The constraints I set

These were decisions, not defaults. Each has an ADR with the
alternatives I considered ([docs/adr/](adr/)):

- **FastAPI + SQLite, one container.** The brief says `docker build` +
  `docker run` — that quietly rules out anything needing a second
  container. SQLite behind SQLAlchemy 2.0 keeps the engine swappable to
  Postgres by changing a URL (ADR-001, ADR-002).
- **Clean at ingest, not at query time.** One place where messy data is
  handled, a database that only ever contains trustworthy rows, and
  query code that stays simple (ADR-003).
- **Every upload returns a full quality report**, and quarantined rows
  stay queryable. No silent fixes, no silent drops (ADR-010, ADR-015).
- **A quality bar that is enforced, not aspirational**: `mypy --strict`,
  ruff with pydocstyle, 90% line+branch coverage as a CI gate, tests
  written in the same phase as the code they test, and an ADR for every
  architectural decision — including ones made mid-implementation. If a
  rule can't be checked by a tool or a test, it isn't a rule. The full
  mapping of rule → checking tool → CI gate is in
  [PLAN.md](PLAN.md) §6.1.

## 3. How the agent team was structured

This is the part I'd actually want to talk about in an interview,
because it's a management problem, not a coding problem.

**Contracts first.** A short serial phase produced the repo skeleton and
froze every interface: Pydantic schemas, function signatures, table
definitions, router paths — committed as stubs. Only then did four
agents work in parallel (data rules, ingest pipeline, query endpoints,
documentation), each owning an exclusive set of files. Merge conflicts
weren't resolved; they were made structurally impossible. The full
specification and the verbatim prompt that launched the team are
appended as [PLAN.md](PLAN.md) and
[KICKOFF_PROMPT.md](KICKOFF_PROMPT.md). One honest deviation from that
prompt: it asked for one commit per lane, but the four parallel lanes
landed merged as a single implementation commit — the phase structure
(scaffold → implement → e2e → review fixes → docs) is visible in the
history, the per-lane boundaries are not. If you want to audit lane
ownership, the exclusive file sets are specified in PLAN.md §7.1.

**Capability matched to risk.** Not every task got the same model. The
data-rules module — where a subtle mistake silently corrupts data — got
a stronger model than the well-specified CRUD lanes. The strongest model
I had went to the adversarial reviewer, on the theory that verification
is the hardest job in the pipeline and a weak reviewer just
rubber-stamps.

**Independent verification, twice.** The expected ingest numbers for the
real files were derived two separate ways: once by the service, once by
a standalone stdlib-only script
(`scripts/generate_expected_counts.py`) that reimplements the documented
rules without importing any service code. The e2e suite asserts they
agree exactly. Separately, a review pass re-derived the acceptance
checklist from the spec and attacked the implementation with hostile
inputs rather than trusting any agent's self-reported results.

## 4. What the review actually caught

I think this is the strongest evidence the process works, so I'm not
hiding it: the adversarial pass found ten confirmed problems in work
that all prior gates had passed, including two real runtime defects —
a non-UTF-8 upload returned a 500 instead of a clean 400, and a
negative `limit` on the quarantine endpoint disabled SQLite's row cap
entirely, bypassing pagination. Both are fixed and both now have
regression tests (`test_non_utf8_upload_returns_400_and_leaves_data_intact`,
`test_quarantine_pagination_rejects_non_positive_bounds`).

The same pass also caught *me*: several counts in my original planning
estimates were wrong. Float-form item numbers are 1,994 rows, not the
~650 I first estimated; unknown-item references are 2,181, not ~950;
and my "3,600 referential gaps" figure turned out to be an artifact of
comparing dirty strings — the true, normalized gap is 327 rows. An
entire defect class (1,299 order windows with no purchase price) wasn't
in my original catalog at all. The repo's docs carry the measured
numbers; the planning appendix still shows my original estimates,
because the delta between them is honest and instructive.

## 5. Judgment calls I'd defend in person

- **Fractional inventory is stored exactly** (16.4 stays 16.4, flagged,
  rounded only for display). Rounding at ingest destroys information I
  can't get back, and the fraction probably means something —
  weight-based items, partial crates (ADR-008).
- **"Order −5 pieces" is quarantined, not clamped.** Turning −5 into 0
  or 5 would be inventing data. The report makes the exclusion visible
  so someone can chase the upstream bug (Q1).
- **A recommendation without an order window is loaded and flagged**,
  not hidden — nothing about the row itself is wrong, only its
  cross-file context (D9). A window without a purchase price *is*
  quarantined — an unpriceable order window can't support the one
  decision it exists for (ADR-017).
- **Re-ingest replaces, never merges.** Idempotent, predictable, and
  the failure mode (you re-upload the wrong file) is recoverable by
  re-uploading the right one (ADR-009).

## 6. What I'd do differently for production

SQLite and replace-per-dataset are right for this brief and wrong for
production scale: the migration path is Postgres (one connection-string
change by design), versioned ingests instead of replacement, auth in
front of the write endpoints, and real observability instead of logs.
I'd also revisit day-first date parsing the moment a second data source
appears — it's proven correct for *these* files (`23/01/2024` exists,
month 23 doesn't), but it's a per-source policy, not a universal truth.

## Where to go from here

[README.md](../README.md) for running it; [TEST_PLAN.md](TEST_PLAN.md)
for what the tests check in plain language;
[ARCHITECTURE.md](ARCHITECTURE.md) for diagrams;
[PROBLEM_ANALYSIS.md](PROBLEM_ANALYSIS.md) for the domain framing; the
[ADRs](adr/) for every decision with its alternatives.
