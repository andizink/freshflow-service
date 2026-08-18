# Start your review here

This repository contains more documentation than a take-home usually
carries, mostly because part of what it demonstrates is not just the
solution, but the complete (AI-directed) process I followed to create it.
You should not have to read all of it to evaluate the submission. 
This page is the map: what to run, what to
read, and what to skip, budgeted by the time you want to allocate to the review.

The one principle this repo asks of you: **don't trust the prose —
verify it.**
I tried to make every claim below reproducible with one command.

## If you have 10 minutes

Run the claim verifier. It re-derives every number the README asserts
and prints PASS/FAIL per claim:

```bash
uv sync --all-groups
./scripts/verify_claims.sh
```

The script checks the eight claims below and prints one PASS/FAIL line
per claim, using the same IDs:

| ID | Claim | How it is checked |
|---|---|---|
| C1 | `ruff check` is clean | runs it |
| C2 | `ruff format --check` is clean | runs it |
| C3 | `mypy --strict` is clean | runs it |
| C4 | The test suite is exactly 416 tests | `pytest --collect-only` count |
| C5 | Unit + integration tests pass with ≥90% branch coverage (measured ~97%) | runs the suite with the CI coverage gate |
| C6 | Ingesting the real CSVs yields exactly the README's ingest table (received / loaded / deduplicated / quarantined per dataset) | e2e suite asserts every report field against the pinned `tests/e2e/expected_counts.json` |
| C7 | Those pinned counts aren't circular — they re-derive from a standalone, stdlib-only script that never imports `app/` | re-runs `scripts/generate_expected_counts.py` and requires a byte-identical fixture |
| C8 | The README's sample response is a real capture: `store_a` / `2024-01-01` returns 48 recommendations, item 1001 with quantity 18, delivery 2024-01-02, inventory 16, prices 0.93 / 1.47 | ingests all four CSVs into a throwaway DB and asserts each field |

Then skim [the five judgment calls](#the-five-judgment-calls-that-matter)
below — they are the substance of the design.

## If you have 30 minutes

Everything above, plus run the service and poke it yourself:

```bash
docker build -t freshflow . && docker run -p 8000:8000 freshflow
# (or: uv run uvicorn app.main:app --port 8000)
BASE_URL=http://localhost:8000 ./scripts/load_all.sh
```

Suggested probes, in ascending nastiness: query a store/day
(`/api/v1/stores/store_a/recommendations?day=2024-01-01`), re-fetch an
ingest report by id, page through a quarantine listing
(`/api/v1/ingest/{ingest_id}/quarantine`), upload the wrong CSV to the
wrong endpoint, upload a non-UTF-8 file, and re-ingest a dataset twice —
then read [DATA_GUIDE.md](docs/DATA_GUIDE.md) §2, the defect catalog D1–D10,
to check the behavior you just saw against the documented intent.

## If you have 90 minutes

Everything above, plus:

- **Code** (~2.8k lines): read `app/ingest/rules.py` (the heart — rules
  N1–N7/Q1–Q5), then `app/ingest/service.py` (atomic replace + report
  semantics), then `app/recommendations/service.py` (the enrichment
  joins). Routers, models, and schemas are thin and hold few surprises.
- **Process**: [APPROACH.md](docs/APPROACH.md) — how the build was directed,
  what the adversarial review caught (including in my own planning
  numbers), and the judgment calls I'd defend in person.
- **Decisions**: the [ADR index](docs/adr/) — read ADR-003 (clean at ingest),
  ADR-009 (replace-per-dataset), ADR-010 (quarantine persistence),
  ADR-015 (report semantics), ADR-017 (required prices). The rest are
  context for specific choices; skim titles and pull what you care about.

## The five judgment calls that matter

Each one line here; each defended with alternatives in its linked record.

1. **"Order −5 pieces" is quarantined, not clamped** — inventing a 0
   or 5 would be fabricating data; the exclusion is visible in the
   report so someone can chase the upstream bug. (Q1, DATA_GUIDE §3)
2. **Items missing from the catalog (1099, 9901–9903) are quarantined,
   not served nameless** — an unpriceable, unnameable recommendation
   helps no one; quarantine is reversible by re-uploading the catalog
   plus the file. This is the call most worth challenging in an
   interview. (Q2, DATA_GUIDE §3)
3. **A recommendation without an order window is loaded and flagged
   `orderable: false`; a window without a purchase price is quarantined**
   — the row itself is valid in the first case, unpriceable in the
   second. Note the deliberate consequence: quarantining ~1.9k window
   rows makes ~1.2k loaded recommendations window-less (vs 327 raw
   mismatches). (D9/D10, ADR-017, DATA_GUIDE §3)
4. **Fractional inventory (16.4 pieces, 87% of the file) is stored
   exactly, rounded only for display** — rounding at ingest destroys
   information that is probably signal (weight-based items), not noise.
   (ADR-008)
5. **Re-ingest replaces the dataset atomically, never merges** —
   idempotent and predictable; the failure mode (wrong file) is
   recoverable by re-uploading the right one. (ADR-009)

## Document map

**Load-bearing** (read these to evaluate the submission):

| Doc | What it is | Read when |
|---|---|---|
| [README](README.md) | Run instructions, API table, headline numbers | First contact |
| this guide | Time-boxed review paths | First contact |
| [DATA_GUIDE.md](docs/DATA_GUIDE.md) | Defect catalog D1–D10 + what the pipeline does per defect | 30-min pass |
| [APPROACH.md](docs/APPROACH.md) | How the build was directed; what review caught | AI-process assessment |
| [ADRs](docs/adr/) | Each non-obvious decision with alternatives | As needed per decision |

**Supporting** (deepen specific angles):

| Doc | What it is |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Runtime/component/ER diagrams, sequences |
| [DATA_QUALITY.md](docs/DATA_QUALITY.md) | Formal defect → rule → code → test traceability matrix |
| [TEST_PLAN.md](docs/TEST_PLAN.md) | Plain-language description of integration/e2e cases |
| [PROBLEM_ANALYSIS.md](docs/PROBLEM_ANALYSIS.md) | Domain framing for readers new to grocery ordering |

**Appendix** (historical artifacts, not primary reading — kept verbatim
because APPROACH.md refers to them as evidence, including my original,
later-corrected estimates):

| Doc | What it is |
|---|---|
| [PLAN.md](docs/PLAN.md) | The frozen pre-implementation plan the agent team executed |
| [KICKOFF_PROMPT.md](docs/KICKOFF_PROMPT.md) | The verbatim prompt that launched the build |

## Known limits (so you don't have to rediscover them)

SQLite and replace-per-dataset are right for this brief, wrong for
production scale (ADR-002 §consequences, APPROACH §6). Ingest memory is
bounded by the 50 MB upload cap, not streaming-flat (ADR-016). Quarantine
history accumulates with no retention policy (ADR-010). Request-parameter
validation errors use FastAPI's native 422 shape while domain errors use
RFC 9457 — a deliberate two-shape compromise (ADR-011). Day-first date
parsing is proven for these files, and is a per-source policy, not a
universal truth (ADR-007).
