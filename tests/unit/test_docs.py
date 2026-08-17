"""Documentation meta-tests: structural checks on the ``docs/`` deliverables.

These tests do not judge documentation *content* (that is a human review
concern) — they verify the structural contracts PLAN.md §6.1 and §8 hold
the docs to: every ADR follows the MADR-style section layout and declares a
status, at least 14 ADRs exist, ``ARCHITECTURE.md`` carries the required
number of Mermaid diagrams, and ``DATA_QUALITY.md`` cites every
normalization/quarantine rule ID. Pure stdlib (``pathlib`` + ``re``): no
markdown parser dependency, so these checks stay simple and fast.
"""

import re
from pathlib import Path

#: Repository root, resolved relative to this test file
#: (``tests/unit/test_docs.py`` -> ``tests/unit`` -> ``tests`` -> root).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DOCS_DIR = REPO_ROOT / "docs"
ADR_DIR = DOCS_DIR / "adr"

#: Minimum number of ADR files required (PLAN.md §2, §2.1: ADR-001..012,
#: plus ADR-013/014 for in-flight decisions, and ADR-015/016 added at
#: Phase 4 finalization for ingest report semantics and upload size
#: enforcement).
MIN_ADR_COUNT = 17

#: Section headings every ADR must contain, in MADR style (PLAN.md §2).
REQUIRED_ADR_HEADINGS = (
    "## Context",
    "## Options Considered",
    "## Decision",
    "## Consequences",
)

#: Minimum number of ```mermaid fenced code blocks required in
#: ARCHITECTURE.md (PLAN.md §5, §8: container, component, ERD, ingest
#: sequence, request-flow).
MIN_MERMAID_BLOCKS = 5

#: Normalization and quarantine rule IDs that must be traceable in
#: DATA_QUALITY.md (PLAN.md §4.2, §4.3).
REQUIRED_RULE_IDS = (
    "N1",
    "N2",
    "N3",
    "N4",
    "N5",
    "N6",
    "N7",
    "Q1",
    "Q2",
    "Q3",
    "Q4",
    "Q5",
)


def _adr_files() -> list[Path]:
    """Return every ``ADR-*.md`` file in ``docs/adr/``, sorted by name.

    Returns:
        A sorted list of paths to ADR markdown files. Non-ADR files (e.g.
        ``.gitkeep``) are excluded by the glob pattern.
    """
    return sorted(ADR_DIR.glob("ADR-*.md"))


def test_minimum_adr_count_is_met() -> None:
    """docs/adr/ must contain at least MIN_ADR_COUNT ADR files (PLAN.md §2, §8)."""
    adr_files = _adr_files()

    assert len(adr_files) >= MIN_ADR_COUNT, (
        f"expected at least {MIN_ADR_COUNT} ADR files in {ADR_DIR}, "
        f"found {len(adr_files)}: {[f.name for f in adr_files]}"
    )


def test_every_adr_has_required_section_headings() -> None:
    """Each ADR must contain Context, Options Considered, Decision, and Consequences.

    Raises:
        AssertionError: If any ``docs/adr/ADR-*.md`` file is missing one or
            more of the required MADR-style section headings.
    """
    adr_files = _adr_files()
    assert adr_files, f"no ADR files found in {ADR_DIR}"

    missing_by_file: dict[str, list[str]] = {}
    for adr_file in adr_files:
        content = adr_file.read_text(encoding="utf-8")
        missing = [
            heading
            for heading in REQUIRED_ADR_HEADINGS
            if not re.search(rf"^{re.escape(heading)}\s*$", content, flags=re.MULTILINE)
        ]
        if missing:
            missing_by_file[adr_file.name] = missing

    assert not missing_by_file, f"ADR files missing required headings: {missing_by_file}"


def test_every_adr_has_a_status_line() -> None:
    """Each ADR must declare a ``Status:`` line (e.g. ``Status: Accepted``).

    Raises:
        AssertionError: If any ``docs/adr/ADR-*.md`` file has no line
            starting with ``Status:``.
    """
    adr_files = _adr_files()
    assert adr_files, f"no ADR files found in {ADR_DIR}"

    missing_status = [
        adr_file.name
        for adr_file in adr_files
        if not re.search(
            r"^Status:\s*\S+", adr_file.read_text(encoding="utf-8"), flags=re.MULTILINE
        )
    ]

    assert not missing_status, f"ADR files missing a 'Status:' line: {missing_status}"


def test_every_adr_filename_has_a_title_prefix() -> None:
    """Each ADR file must start with a top-level ``# ADR-NNN: <title>`` heading.

    Raises:
        AssertionError: If any ``docs/adr/ADR-*.md`` file's first heading
            does not match the ``# ADR-NNN: <title>`` pattern.
    """
    adr_files = _adr_files()
    assert adr_files, f"no ADR files found in {ADR_DIR}"

    malformed = [
        adr_file.name
        for adr_file in adr_files
        if not re.search(
            r"^# ADR-\d{3,}: .+$", adr_file.read_text(encoding="utf-8"), flags=re.MULTILINE
        )
    ]

    assert not malformed, f"ADR files missing a '# ADR-NNN: <title>' heading: {malformed}"


def test_architecture_doc_has_minimum_mermaid_diagrams() -> None:
    """docs/ARCHITECTURE.md must contain at least 5 ```mermaid fenced blocks.

    Raises:
        AssertionError: If ``docs/ARCHITECTURE.md`` is missing or contains
            fewer than :data:`MIN_MERMAID_BLOCKS` mermaid code blocks.
    """
    architecture_doc = DOCS_DIR / "ARCHITECTURE.md"
    assert architecture_doc.is_file(), f"missing {architecture_doc}"

    content = architecture_doc.read_text(encoding="utf-8")
    mermaid_blocks = re.findall(r"```mermaid\b", content)

    assert len(mermaid_blocks) >= MIN_MERMAID_BLOCKS, (
        f"expected at least {MIN_MERMAID_BLOCKS} ```mermaid blocks in "
        f"{architecture_doc}, found {len(mermaid_blocks)}"
    )


def test_data_quality_doc_mentions_every_rule_id() -> None:
    """docs/DATA_QUALITY.md must mention every rule ID N1-N7 and Q1-Q5.

    Raises:
        AssertionError: If ``docs/DATA_QUALITY.md`` is missing or does not
            mention one or more of :data:`REQUIRED_RULE_IDS`.
    """
    data_quality_doc = DOCS_DIR / "DATA_QUALITY.md"
    assert data_quality_doc.is_file(), f"missing {data_quality_doc}"

    content = data_quality_doc.read_text(encoding="utf-8")

    missing_ids = [
        rule_id for rule_id in REQUIRED_RULE_IDS if not re.search(rf"\b{rule_id}\b", content)
    ]

    assert not missing_ids, f"{data_quality_doc} does not mention rule IDs: {missing_ids}"
