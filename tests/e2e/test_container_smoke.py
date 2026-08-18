"""Container smoke test: build the Docker image, run it, and exercise the API.

Marked ``@pytest.mark.smoke`` (PLAN.md §6.1). Builds the production image
with ``docker build``, runs it with a Docker-assigned host port (asking
Docker to pick the port avoids guessing a "free" port from the host side,
which Docker Desktop on macOS sometimes refuses to bind) and a fresh Docker
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


def _run_docker(args: list[str]) -> str:
    """Run a docker CLI command, surfacing stderr in any failure.

    ``subprocess.run(..., capture_output=True, check=True)`` swallows the
    daemon's error message into an unread attribute, which turns a clear
    failure ("port is not available", "no space left on device") into an
    opaque ``CalledProcessError``. This wrapper re-raises with the captured
    stderr in the message so a failing run is diagnosable from the pytest
    output alone.

    Args:
        args: The full docker CLI argument list, including ``"docker"``.

    Returns:
        The command's stdout, stripped.

    Raises:
        RuntimeError: If the command exits non-zero, with stderr included.
    """
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _container_host_port(container_name: str) -> int:
    """Return the host port Docker mapped to the container's port 8000.

    Args:
        container_name: The running container's name.

    Returns:
        The host TCP port number.

    Raises:
        RuntimeError: If ``docker port`` fails or prints nothing parseable.
    """
    # Output looks like "0.0.0.0:55012" (possibly one line per address family).
    output = _run_docker(["docker", "port", container_name, "8000"])
    first_line = output.splitlines()[0] if output else ""
    try:
        return int(first_line.rsplit(":", 1)[1])
    except (IndexError, ValueError) as exc:
        raise RuntimeError(
            f"could not parse host port from docker port output: {output!r}"
        ) from exc


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

    subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, "."],
        cwd=REPO_ROOT,
        check=True,
    )

    try:
        _run_docker(["docker", "volume", "create", volume_name])
        _run_docker(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                # Let Docker assign the host port: guessing a free port from
                # the host side races against Docker Desktop's port
                # forwarder, which can refuse a port the OS just reported
                # as available.
                "-p",
                "127.0.0.1::8000",
                "-v",
                f"{volume_name}:/data",
                IMAGE_TAG,
            ]
        )
        port = _container_host_port(container_name)
        base_url = f"http://127.0.0.1:{port}"

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

        user = _run_docker(["docker", "inspect", IMAGE_TAG, "--format", "{{ .Config.User }}"])
        assert user and user != "root", f"image runs as root or has no USER set: {user!r}"

        healthcheck = _run_docker(
            ["docker", "inspect", IMAGE_TAG, "--format", "{{ .Config.Healthcheck }}"]
        )
        assert "CMD" in healthcheck, f"image has no HEALTHCHECK: {healthcheck!r}"
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
        subprocess.run(["docker", "volume", "rm", "-f", volume_name], capture_output=True)
