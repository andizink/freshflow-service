"""RFC 9457 ``application/problem+json`` error shape (ADR-011)."""

from pydantic import BaseModel, ConfigDict


class ProblemDetail(BaseModel):
    """An RFC 9457 problem details object.

    Attributes:
        type: A URI reference identifying the problem type; ``"about:blank"``
            when no more specific type is defined.
        title: A short, human-readable summary of the problem type.
        status: The HTTP status code for this occurrence of the problem.
        detail: A human-readable explanation specific to this occurrence.
    """

    model_config = ConfigDict(frozen=True)

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
