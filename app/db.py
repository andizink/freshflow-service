"""SQLAlchemy engine, session management, and declarative base.

The module keeps one module-level "current" engine/session-factory pair,
built lazily from :func:`app.config.get_settings` on first use. Tests that
need an isolated database call :func:`configure_engine` with a dedicated
(typically ``tmp_path``-backed SQLite) engine *before* the FastAPI app is
exercised — see ``tests/conftest.py`` for the reference fixture, which
overrides the :func:`get_session` dependency directly so production code
never has to guess which engine is "current".
"""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base class shared by every ORM model."""


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def create_engine_from_settings() -> Engine:
    """Build a SQLAlchemy engine for the configured SQLite database file.

    Returns:
        A new :class:`~sqlalchemy.Engine` pointed at ``settings.db_path``,
        configured for use from multiple threads (as FastAPI/Uvicorn worker
        threads require for SQLite).
    """
    settings = get_settings()
    return create_engine(
        f"sqlite:///{settings.db_path}",
        connect_args={"check_same_thread": False},
    )


def configure_engine(engine: Engine) -> None:
    """Install ``engine`` as the process-wide current engine.

    This rebuilds the session factory bound to the new engine. Intended for
    application startup (:func:`app.main.create_app`) and for tests that
    need an isolated, disposable database.

    Args:
        engine: The engine to install as current.
    """
    global _engine, _session_factory
    _engine = engine
    _session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_engine() -> Engine:
    """Return the current engine, lazily creating one from settings.

    Returns:
        The process-wide current :class:`~sqlalchemy.Engine`.
    """
    if _engine is None:
        configure_engine(create_engine_from_settings())
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the current session factory, lazily creating one from settings.

    Returns:
        The process-wide current :class:`~sqlalchemy.orm.sessionmaker`.
    """
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


def init_db(engine: Engine) -> None:
    """Create all tables registered on :class:`Base` for ``engine``.

    Args:
        engine: The engine whose database should receive the schema.
    """
    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped SQLAlchemy session.

    Yields:
        A :class:`~sqlalchemy.orm.Session` bound to the current engine. The
        session is closed automatically when the request completes.
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


#: FastAPI dependency annotation for injecting a request-scoped session.
#: Using ``Annotated`` (rather than a ``Depends(...)`` call as a default
#: value) is the current FastAPI-recommended style and keeps route
#: signatures free of B008-flagged mutable-looking default calls.
SessionDep = Annotated[Session, Depends(get_session)]
