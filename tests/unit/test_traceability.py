"""Meta-test: every rule ID is traceable from the rule table to code and tests.

PLAN.md §6.1 requires that rule IDs N1-N7 and Q1-Q5 are not just prose: each
must be cited in a docstring inside the ``app/ingest`` package (so the code
says which rule it implements) and must be visible in ``tests/unit`` (so a
reviewer can find the test that pins it). Presence is asserted across the
whole package rather than in one specific function, because the rules are
implemented across ``normalize.py``, ``rules.py``, and ``service.py`` and
may legitimately move between them.
"""

import ast
from pathlib import Path

import pytest

import app.ingest

RULE_IDS = [f"N{index}" for index in range(1, 8)] + [f"Q{index}" for index in range(1, 6)]

APP_INGEST_DIR = Path(app.ingest.__file__).parent
TESTS_UNIT_DIR = Path(__file__).parent


def _docstrings(path: Path) -> list[str]:
    """Return every module/class/function docstring in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    documented = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, documented):
            docstring = ast.get_docstring(node)
            if docstring:
                found.append(docstring)
    return found


def _package_docstrings(directory: Path) -> str:
    """Return all docstrings in ``directory``'s Python modules as one blob."""
    return "\n".join(
        docstring for path in sorted(directory.glob("*.py")) for docstring in _docstrings(path)
    )


def test_rule_id_list_is_complete() -> None:
    assert RULE_IDS == ["N1", "N2", "N3", "N4", "N5", "N6", "N7", "Q1", "Q2", "Q3", "Q4", "Q5"]


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_rule_is_cited_in_an_app_ingest_docstring(rule_id: str) -> None:
    docstrings = _package_docstrings(APP_INGEST_DIR)

    assert rule_id in docstrings, f"{rule_id} is not cited in any app/ingest docstring"


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_rule_is_visible_in_a_unit_test_module(rule_id: str) -> None:
    test_files = sorted(TESTS_UNIT_DIR.glob("test_*.py"))
    named = [path for path in test_files if rule_id.lower() in path.name.lower()]
    documented = [path for path in test_files if any(rule_id in doc for doc in _docstrings(path))]

    assert named or documented, f"{rule_id} appears in no unit-test file name or docstring"


def test_every_rule_module_has_a_module_docstring() -> None:
    for path in sorted(APP_INGEST_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        assert ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))), path.name
