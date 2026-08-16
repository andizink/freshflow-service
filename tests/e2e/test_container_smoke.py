"""Container smoke test: build the Docker image, run it, and exercise the API.

Marked ``@pytest.mark.smoke`` (PLAN.md §6.1). Builds the production image
with ``docker build``, runs it on a free host port with a fresh Docker
volume mounted at ``/data`` (matching ``FRESHFLOW_DB_PATH=/data/freshflow.db``
from the ``Dockerfile``), polls ``/health`` until the container is ready,
ingests the four real ``data/`` CSVs plus one recommendations query through
the running container (via ``httpx``, not the in-process ``TestClient``),
asserts the same ``tests/e2e/expected_counts.json`` numbers the
``test_real_data.py`` in-process e2e suite asserts, and inspects the image
for the non-root ``User`` and ``Healthcheck`` PLAN.md §6.1 requires -
cleaning up the container and volume in a ``finally`` block regardless of
outcome.

Skips cleanly with ``pytest.skip`` when the Docker daemon is unreachable,
which is always true in this development sandbox: this module must still
import and collect successfully there, so CI's ``docker`` job
(``.github/workflows/ci.yml``, which runs ``hadolint`` then
``docker build`` before ``pytest -m smoke``) is the only place this test
actually executes its Docker steps.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
EXPECTED_COUNTS_PATH = Path(__file__).resolve().parent / "expected_counts.json"

#: Tag used for the image built by this test. Distinct from any tag CI's
#: ``docker`` job may have already built, so this test always builds its own
#: fresh image and can safely be run standalone.
IMAGE_TAG = "freshflow-service:smoke-test"

#: ``(dataset, source CSV filename)`` pairs, in ingest order (items first).
DATASET_FILES: tuple[tuple[str, str], ...] = (
    ("items", "items.csv"),
    ("inventory", "inventory.csv"),
    ("orderable-items", "orderable_items.csv"),
    ("order-recommendations", "order_recommendations.csv"),
)

#: How long to wait for the container's ``/health`` endpoint to respond.
HEALTH_TIMEOUT_SECONDS = 60.0

#: Report fields checked against ``expected_counts.json`` for each dataset.
_REPORT_FIELDS = (
    "received_rows",
    "loaded_rows",
    "deduplicated_rows",
    "quarantined_rows",
    "normalizations",
    "quarantine_summary",
)

pytestmark = pytest.mark.smoke


def _docker_available() -> bool:
    """Return whether a Docker daemon is reachable from this environment.

    Returns:
        ``True`` if the ``docker`` CLI is on ``PATH`` and ``docker info``
        succeeds against a live daemon within a short timeout; ``False``
        otherwise (missing CLI, unreachable daemon, or any subprocess
        error).
    """
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    return True


def _free_port() -> int:
    """Find a currently-unused local TCP port.

    Returns:
        A port number the OS reports as free at the moment of the call.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _load_expected_counts() -> dict[str, dict[str, object]]:
    """Load the expected-counts fixture, stripping the ``_note`` metadata key.

    Returns:
        A mapping of dataset key to its expected ``IngestReport`` fields.
    """
    raw = json.loads(EXPECTED_COUNTS_PATH.read_text())
    return {key: value for key, value in raw.items() if key != "_note"}


def _wait_for_health(base_url: str, timeout: float) -> None:
    """Poll ``{base_url}/health`` until it responds 200 or ``timeout`` elapses.

    Args:
        base_url: The container's base URL.
        timeout: Maximum time to wait, in seconds.

    Raises:
        TimeoutError: If the endpoint never became healthy within
            ``timeout``.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=2.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.5)
    raise TimeoutError(
        f"container did not become healthy within {timeout}s (last error: {last_error})"
    )


def test_container_builds_runs_and_serves_real_data() -> None:
    """Build, run, and exercise the container image against the real data.

    Skips (does not fail) when Docker is unavailable. When it runs, always
    tears down the container and volume it created, even on assertion
    failure.
    """
    if not _docker_available():
        pytest.skip("docker daemon is unreachable in this environment")

    run_id = uuid.uuid4().hex[:8]
    container_name = f"freshflow-smoke-{run_id}"
    volume_name = f"freshflow-smoke-data-{run_id}"
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, "."],
        cwd=REPO_ROOT,
        check=True,
    )

    try:
        subprocess.run(["docker", "volume", "create", volume_name], check=True, capture_output=True)
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                "-p",
                f"{port}:8000",
                "-v",
                f"{volume_name}:/data",
                IMAGE_TAG,
            ],
            check=True,
            capture_output=True,
        )

        _wait_for_health(base_url, HEALTH_TIMEOUT_SECONDS)

        expected_counts = _load_expected_counts()
        with httpx.Client(timeout=60.0) as client:
            for dataset, filename in DATASET_FILES:
                path = DATA_DIR / filename
                with path.open("rb") as fh:
                    response = client.post(
                        f"{base_url}/api/v1/ingest/{dataset}",
                        files={"file": (filename, fh, "text/csv")},
                    )
                assert response.status_code == 200, response.text
                report = response.json()
                expected = expected_counts[dataset]
                for field in _REPORT_FIELDS:
                    assert report[field] == expected[field], (
                        f"{dataset}.{field}: got {report[field]!r}, expected {expected[field]!r}"
                    )

            recommendations_response = client.get(
                f"{base_url}/api/v1/stores/store_a/recommendations",
                params={"day": "2024-01-01"},
            )
            assert recommendations_response.status_code == 200
            body = recommendations_response.json()
            by_item = {item["item_number"]: item for item in body["recommendations"]}
            assert 1001 in by_item
            assert by_item[1001]["recommended_quantity"] == 18
            assert by_item[1001]["item_name"] == "Organic Bananas"

        user = subprocess.run(
            ["docker", "inspect", IMAGE_TAG, "--format", "{{ .Config.User }}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert user and user != "root", f"image runs as root or has no USER set: {user!r}"

        healthcheck = subprocess.run(
            ["docker", "inspect", IMAGE_TAG, "--format", "{{ .Config.Healthcheck }}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert "CMD" in healthcheck, f"image has no HEALTHCHECK: {healthcheck!r}"
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
        subprocess.run(["docker", "volume", "rm", "-f", volume_name], capture_output=True)
