"""FastAPI application factory, lifespan, routers, and error handling.

Structured logging is configured here (from ``settings.log_level``) rather
than left to library defaults — no module in this codebase uses ``print``.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import get_engine, init_db
from app.ingest.parser import HeaderError
from app.ingest.router import router as ingest_router
from app.recommendations.router import router as recommendations_router
from app.recommendations.service import StoreNotFoundError
from app.schemas.errors import ProblemDetail
from app.stores.router import router as stores_router

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def _configure_logging() -> None:
    """Configure process-wide structured logging from settings.

    Idempotent: safe to call multiple times (e.g. once per app instance in
    tests) since :func:`logging.basicConfig` is a no-op after the first
    successful call unless ``force=True``.
    """
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: initialize the database schema on startup.

    Args:
        app: The FastAPI application instance (unused, required by the
            lifespan protocol).

    Yields:
        Control back to FastAPI for the lifetime of the application.
    """
    logger.info("starting freshflow-service")
    init_db(get_engine())
    yield
    logger.info("stopping freshflow-service")


def _problem_response(status: int, title: str, detail: str | None = None) -> JSONResponse:
    """Build an RFC 9457 ``application/problem+json`` response.

    Args:
        status: The HTTP status code.
        title: A short, human-readable summary of the problem type.
        detail: A human-readable explanation specific to this occurrence.

    Returns:
        A :class:`~fastapi.responses.JSONResponse` with the problem+json
        content type and body.
    """
    problem = ProblemDetail(title=title, status=status, detail=detail)
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
    )


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Returns:
        A fully configured :class:`~fastapi.FastAPI` instance: routers
        mounted under :data:`API_PREFIX`, ``/health``, and RFC 9457 error
        handlers registered.
    """
    _configure_logging()

    app = FastAPI(title="FreshFlow Service", version="1.0.0", lifespan=lifespan)

    app.include_router(ingest_router, prefix=API_PREFIX)
    app.include_router(recommendations_router, prefix=API_PREFIX)
    app.include_router(stores_router, prefix=API_PREFIX)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe used by the Docker ``HEALTHCHECK``.

        Returns:
            A minimal status payload.
        """
        return {"status": "ok"}

    @app.exception_handler(StoreNotFoundError)
    async def handle_store_not_found(request: Request, exc: StoreNotFoundError) -> JSONResponse:
        """Map :class:`StoreNotFoundError` to a 404 problem+json response.

        Args:
            request: The incoming request (unused, required by the
                exception handler protocol).
            exc: The raised error.

        Returns:
            A 404 RFC 9457 problem response.
        """
        return _problem_response(404, "Store not found", str(exc))

    @app.exception_handler(HeaderError)
    async def handle_header_error(request: Request, exc: HeaderError) -> JSONResponse:
        """Map :class:`HeaderError` to a 400 problem+json response.

        Args:
            request: The incoming request (unused, required by the
                exception handler protocol).
            exc: The raised error.

        Returns:
            A 400 RFC 9457 problem response.
        """
        return _problem_response(400, "Invalid CSV header", str(exc))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Map any otherwise-unhandled exception to a 500 problem+json response.

        Args:
            request: The incoming request (unused, required by the
                exception handler protocol).
            exc: The raised error.

        Returns:
            A 500 RFC 9457 problem response.
        """
        logger.exception("unhandled exception", exc_info=exc)
        return _problem_response(500, "Internal server error")

    return app


app: FastAPI = create_app()
