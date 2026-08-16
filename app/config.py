"""Application configuration via environment variables.

Settings are loaded once and cached; every module that needs configuration
should call :func:`get_settings` rather than constructing :class:`Settings`
directly, so the whole process shares one immutable configuration snapshot.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the FreshFlow service.

    Attributes:
        db_path: Filesystem path to the SQLite database file.
        log_level: Python logging level name (e.g. ``"INFO"``, ``"DEBUG"``).
        max_upload_bytes: Maximum accepted size, in bytes, for an ingest
            CSV upload.
    """

    model_config = SettingsConfigDict(env_prefix="FRESHFLOW_", extra="ignore")

    db_path: Path = Path("./freshflow.db")
    log_level: str = "INFO"
    max_upload_bytes: int = 50_000_000


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance.

    Returns:
        The singleton :class:`Settings` built from environment variables.
    """
    return Settings()
