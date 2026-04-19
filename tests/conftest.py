"""Pytest configuration and shared fixtures for pygob tests."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

TESTDATA_DIR = Path(__file__).parent / "testdata"
GO_VERIFY_DIR = Path(__file__).parent.parent  # repo root (go.mod lives here)


def load_testdata(name: str) -> tuple[bytes, dict]:
    """Load a .gob file and its .json sidecar by test case name.

    Returns (gob_bytes, expected_dict).
    """
    gob_path = TESTDATA_DIR / f"{name}.gob"
    json_path = TESTDATA_DIR / f"{name}.json"
    return gob_path.read_bytes(), json.loads(json_path.read_text())


def all_testdata_names() -> list[str]:
    """Return the sorted list of test case names that have both .gob and .json files."""
    names = []
    for gob_file in sorted(TESTDATA_DIR.glob("*.gob")):
        json_file = gob_file.with_suffix(".json")
        if json_file.exists():
            names.append(gob_file.stem)
    return names


@pytest.fixture(scope="session")
def go_verify():
    """Return a callable that cross-validates gob bytes via the Go verifier.

    If Go is not on PATH, the returned callable calls pytest.skip() instead.

    Usage::

        def test_something(go_verify):
            result = go_verify("struct_simple", gob_bytes)
            assert result["ok"] is True
            assert result["value"]["X"] == 22
    """
    go_available = shutil.which("go") is not None

    def _verify(test_name: str, gob_bytes: bytes) -> dict:
        if not go_available:
            pytest.skip("go not available on PATH")

        result = subprocess.run(
            ["go", "run", "./tests/go_verify", test_name],
            input=gob_bytes,
            capture_output=True,
            cwd=GO_VERIFY_DIR,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"go_verify failed for {test_name!r}:\n"
                f"stdout: {result.stdout.decode()}\n"
                f"stderr: {result.stderr.decode()}"
            )
        return json.loads(result.stdout)

    return _verify
