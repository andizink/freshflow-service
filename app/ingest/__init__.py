"""Ingest pipeline: parse → normalize → validate → load (PLAN.md §4, §5).

Submodules:
    parser: Streaming CSV reading and header validation.
    normalize: Pure normalization functions, rules N1-N7.
    rules: Row-level quarantine rules Q1-Q5 and the dedup key function.
    service: Orchestration — parse, normalize, dedup, atomic load, report.
    router: FastAPI routes under ``/ingest``.
"""
