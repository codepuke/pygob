"""Verify that the conftest fixtures load testdata correctly."""

import pytest

from tests.conftest import TESTDATA_DIR, all_testdata_names, load_testdata


def test_testdata_files_exist():
    """All expected .gob files are present alongside .json sidecars."""
    names = all_testdata_names()
    assert len(names) > 0, "No testdata files found"
    for name in names:
        assert (TESTDATA_DIR / f"{name}.gob").exists(), f"Missing {name}.gob"
        assert (TESTDATA_DIR / f"{name}.json").exists(), f"Missing {name}.json"


def test_load_testdata_struct_simple():
    """load_testdata returns non-empty bytes and a valid dict for a known case."""
    gob_bytes, expected = load_testdata("struct_simple")
    assert len(gob_bytes) > 0
    assert expected["type"] == "struct"
    assert expected["gob_type"] == "Point"
    assert expected["value"] == {"X": 22, "Y": 33}


@pytest.mark.parametrize("name", all_testdata_names())
def test_testdata_json_is_valid(name):
    """Every .json sidecar is valid JSON — either a dict with 'type', or a list of such dicts."""
    _, expected = load_testdata(name)
    entries = expected if isinstance(expected, list) else [expected]
    assert len(entries) > 0
    for entry in entries:
        assert "type" in entry


def test_go_verify_fixture_initializes(go_verify):
    """go_verify fixture returns a callable (skips if Go unavailable)."""
    assert callable(go_verify)


def test_go_verify_struct_simple(go_verify):
    """go_verify correctly decodes struct_simple with the Go verifier."""
    gob_bytes, _ = load_testdata("struct_simple")
    result = go_verify("struct_simple", gob_bytes)
    assert result["ok"] is True
    assert result["value"]["X"] == 22
    assert result["value"]["Y"] == 33
