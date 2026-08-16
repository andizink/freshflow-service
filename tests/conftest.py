"""Shared pytest fixtures: isolated SQLite engine, session, and API client.

Each test gets its own SQLite database file inside pytest's per-test
``tmp_path``, installed as the process-wide "current" engine via
``app.db.configure_engine``. This is a deliberate choice documented here
(rather than in the PLAN) because ``app.db`` keeps one module-level
current-engine/session-factory pair (see its module docstring): the
``engine`` fixture below is what makes that pair point at an isolated,
disposable database for the duration of one test, so
``app.main.create_app``'s lifespan (which lazily fetches the "current"
engine on startup) and the ``client`` fixture's explicit
``dependency_overrides`` for ``get_session`` both end up reading/writing
the same isolated database. No test can see another test's data, and
nothing touches the default ``./freshflow.db`` path.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import db
from app.db import get_session, init_db
from app.main import create_app


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """Create, install, and initialize an isolated SQLite engine for one test.

    Args:
        tmp_path: Pytest's per-test temporary directory.

    Yields:
        The isolated engine, already installed via
        :func:`app.db.configure_engine` and schema-initialized.
    """
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    db.configure_engine(test_engine)
    init_db(test_engine)
    try:
        yield test_engine
    finally:
        test_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Provide a SQLAlchemy session bound to the isolated test engine.

    Args:
        engine: The isolated test engine fixture.

    Yields:
        An open session, closed automatically at teardown.
    """
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    test_session = factory()
    try:
        yield test_session
    finally:
        test_session.close()


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    """Provide a FastAPI TestClient wired to the isolated test engine.

    Overrides the ``get_session`` dependency so every request in a test
    uses the same isolated engine as the ``session``/``engine`` fixtures,
    independent of ``app.db``'s module-level "current" session factory.

    Args:
        engine: The isolated test engine fixture.

    Yields:
        A ``TestClient`` for a freshly constructed app instance.
    """
    app: FastAPI = create_app()
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _get_session_override() -> Iterator[Session]:
        test_session = factory()
        try:
            yield test_session
        finally:
            test_session.close()

    app.dependency_overrides[get_session] = _get_session_override
    with TestClient(app) as test_client:
        yield test_client
