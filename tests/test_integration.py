"""Task 6.2 — Full integration tests.

Three layers:
1.  Decode every .gob file in testdata/ and assert against its .json sidecar.
2.  Encode Python values → decode → verify values match (round-trip).
3.  Byte-level comparison for deterministic cases (scalars, simple structs).

Edge cases covered: empty collections, zero-valued fields, very large integers,
Unicode strings.
"""

from __future__ import annotations

import base64
import io
import math
from pathlib import Path
from typing import Any

import pytest

import pygob
from pygob import (
    GOB_BOOL,
    GOB_BYTES,
    GOB_COMPLEX,
    GOB_FLOAT,
    GOB_INT,
    GOB_STRING,
    GOB_UINT,
    Decoder,
    Encoder,
    GobEncoded,
    GobStruct,
    Schema,
    UInt,
)
from tests.conftest import all_testdata_names, load_testdata

TESTDATA = Path(__file__).parent / "testdata"


# ---------------------------------------------------------------------------
# JSON sidecar comparison helpers
# ---------------------------------------------------------------------------


def _assert_value_matches(decoded: Any, spec: dict) -> None:
    """Recursively assert that *decoded* matches the JSON *spec* dict.

    *spec* must be a parsed JSON sidecar (or a value-spec sub-dict for nested
    struct assertions).
    """
    t = spec["type"]

    if t == "bool":
        assert decoded is spec["value"], f"bool: {decoded!r} != {spec['value']!r}"

    elif t == "int":
        assert decoded == spec["value"], f"int: {decoded!r} != {spec['value']!r}"
        assert isinstance(decoded, int) and not isinstance(decoded, bool)

    elif t == "uint":
        assert decoded == spec["value"], f"uint: {decoded!r} != {spec['value']!r}"
        assert isinstance(decoded, int) and not isinstance(decoded, bool)

    elif t == "float":
        expected = spec["value"]
        if expected == 0:
            assert decoded == 0.0 and isinstance(decoded, float)
        elif math.isnan(expected):
            assert math.isnan(decoded)
        else:
            assert math.isclose(decoded, expected, rel_tol=1e-9), (
                f"float: {decoded!r} ≉ {expected!r}"
            )

    elif t == "complex":
        expected_r = spec["value"]["real"]
        expected_i = spec["value"]["imag"]
        assert math.isclose(decoded.real, expected_r, rel_tol=1e-9)
        assert math.isclose(decoded.imag, expected_i, rel_tol=1e-9)

    elif t == "string":
        assert decoded == spec["value"]
        assert isinstance(decoded, str)

    elif t == "bytes":
        # JSON sidecars store bytes as base64
        expected = base64.b64decode(spec["value"])
        assert decoded == expected
        assert isinstance(decoded, bytes)

    elif t == "struct":
        _assert_struct_matches(decoded, spec)

    elif t in ("slice", "array"):
        assert isinstance(decoded, list), f"expected list, got {type(decoded).__name__}"
        assert len(decoded) == len(spec["value"])
        for i, (item, expected_item) in enumerate(zip(decoded, spec["value"])):
            _assert_element_matches(item, expected_item, spec.get("elem_type"), spec)

    elif t == "map":
        assert isinstance(decoded, dict)
        expected_map = spec["value"]
        assert len(decoded) == len(expected_map)
        for k, v in decoded.items():
            # JSON map keys are always strings; Go int keys come through as int
            str_key = str(k)
            assert str_key in expected_map, f"unexpected key {k!r}"
            expected_v = expected_map[str_key]
            _assert_element_matches(v, expected_v, spec.get("elem_type"), spec)

    elif t == "gob_encoded":
        assert isinstance(decoded, GobEncoded)
        assert decoded.type_name == spec["gob_type"]
        assert len(decoded.data) > 0

    else:
        pytest.fail(f"Unknown spec type: {t!r}")


def _assert_struct_matches(decoded: Any, spec: dict) -> None:
    """Assert a decoded GobStruct matches a struct-type spec."""
    assert isinstance(decoded, GobStruct), (
        f"expected GobStruct, got {type(decoded).__name__}"
    )
    assert decoded.gob_type == spec["gob_type"], (
        f"gob_type: {decoded.gob_type!r} != {spec['gob_type']!r}"
    )
    expected_value = spec["value"]
    for field_name, expected_field_value in expected_value.items():
        if field_name == "gob_type":
            # interface fields carry a "gob_type" key in the JSON spec
            continue
        assert field_name in decoded, f"missing field {field_name!r}"
        actual = decoded[field_name]
        field_type = spec.get("fields", {}).get(field_name)

        if isinstance(expected_field_value, dict) and expected_field_value.get("type") == "gob_encoded":
            # Nested GobEncoded field (e.g. UUID, time.Time inside a struct)
            assert isinstance(actual, GobEncoded), (
                f"field {field_name!r}: expected GobEncoded, got {type(actual).__name__}"
            )
            assert actual.type_name == expected_field_value["gob_type"], (
                f"field {field_name!r}: type_name {actual.type_name!r} != {expected_field_value['gob_type']!r}"
            )
            assert len(actual.data) > 0
        elif isinstance(expected_field_value, dict) and "gob_type" in expected_field_value:
            # Nested interface value: a struct inside interface{}
            assert isinstance(actual, GobStruct)
            assert actual.gob_type == expected_field_value["gob_type"]
            for k, v in expected_field_value.items():
                if k == "gob_type":
                    continue
                assert actual[k] == v, f"interface inner field {k!r}: {actual[k]!r} != {v!r}"
        elif isinstance(expected_field_value, dict):
            # Nested struct field
            assert isinstance(actual, GobStruct), (
                f"field {field_name!r}: expected GobStruct, got {type(actual).__name__}"
            )
            for k, v in expected_field_value.items():
                assert actual[k] == v, f"nested field {k!r}: {actual[k]!r} != {v!r}"
        elif field_type == "float":
            assert math.isclose(actual, expected_field_value, rel_tol=1e-9), (
                f"field {field_name!r}: {actual!r} ≉ {expected_field_value!r}"
            )
        else:
            assert actual == expected_field_value, (
                f"field {field_name!r}: {actual!r} != {expected_field_value!r}"
            )


def _assert_element_matches(actual: Any, expected: Any, elem_type: str | None, spec: dict) -> None:
    """Assert a single list/map element matches its JSON-spec expected value."""
    if elem_type == "struct":
        # Reconstruct a minimal struct spec for comparison
        assert isinstance(actual, GobStruct)
        if isinstance(expected, dict):
            for k, v in expected.items():
                assert actual[k] == v, f"struct element field {k!r}: {actual[k]!r} != {v!r}"
    elif elem_type == "float":
        assert math.isclose(actual, expected, rel_tol=1e-9)
    else:
        assert actual == expected, f"element: {actual!r} != {expected!r}"


# ---------------------------------------------------------------------------
# 1. Parametrized: decode every .gob and assert against .json sidecar
# ---------------------------------------------------------------------------

# Test cases that require special multi-decode handling
_MULTI_MESSAGE_CASES = frozenset({"multi_message"})


def _decode_testcase(name: str) -> Any:
    """Decode a testdata .gob file. Returns list for multi-message cases."""
    gob_bytes, _ = load_testdata(name)
    dec = Decoder(io.BytesIO(gob_bytes))
    if name in _MULTI_MESSAGE_CASES:
        results = []
        try:
            while True:
                results.append(dec.decode())
        except Exception:
            pass
        return results
    return dec.decode()


@pytest.mark.parametrize("name", all_testdata_names())
def test_decode_testdata(name: str) -> None:
    """Decode every .gob file in testdata/ and assert against its .json sidecar."""
    gob_bytes, spec = load_testdata(name)
    dec = Decoder(io.BytesIO(gob_bytes))

    if name in _MULTI_MESSAGE_CASES:
        # spec is a list of struct specs
        assert isinstance(spec, list)
        results = []
        for _ in spec:
            results.append(dec.decode())
        assert len(results) == len(spec)
        for decoded, item_spec in zip(results, spec):
            _assert_value_matches(decoded, item_spec)
    else:
        decoded = dec.decode()
        _assert_value_matches(decoded, spec)


# ---------------------------------------------------------------------------
# 2. Parametrized round-trip: encode Python values → decode → verify
# ---------------------------------------------------------------------------

# Each entry: (test_id, value, encode_kwargs, assert_fn)
# assert_fn(decoded) raises AssertionError on mismatch


def _rt(test_id, value, assert_fn, **encode_kwargs):
    return pytest.param(value, encode_kwargs, assert_fn, id=test_id)


def _simple(expected):
    """Return an assert_fn that checks decoded == expected."""
    def _check(decoded):
        assert decoded == expected
    return _check


def _close(expected, rel_tol=1e-9):
    """Return an assert_fn for floating-point comparison."""
    def _check(decoded):
        assert math.isclose(decoded, expected, rel_tol=rel_tol)
    return _check


_POINT_SCHEMA = Schema("Point", X=GOB_INT, Y=GOB_INT)
_MIXED_SCHEMA = Schema("MixedStruct", Name=GOB_STRING, Age=GOB_INT, Score=GOB_FLOAT, Active=GOB_BOOL)
_PARTIAL_SCHEMA = Schema("PartialStruct", Name=GOB_STRING, Value=GOB_INT, Extra=GOB_FLOAT)
_INNER_SCHEMA = Schema("Point", X=GOB_INT, Y=GOB_INT)
_OUTER_SCHEMA = Schema("NestedStruct", Label=GOB_STRING, Origin=_INNER_SCHEMA)

ROUND_TRIP_CASES = [
    # --- scalars ---
    _rt("rt_bool_true", True, _simple(True)),
    _rt("rt_bool_false", False, _simple(False)),
    _rt("rt_int_zero", 0, _simple(0)),
    _rt("rt_int_positive", 42, _simple(42)),
    _rt("rt_int_negative", -42, _simple(-42)),
    _rt("rt_int_large", 1 << 60, _simple(1 << 60)),
    _rt("rt_uint", UInt(42), _simple(42)),
    _rt("rt_uint_large", UInt(1 << 63), _simple(1 << 63)),
    _rt("rt_float", 3.14159, _close(3.14159)),
    _rt("rt_float_zero", 0.0, _simple(0.0)),
    _rt("rt_float_negative", -273.15, _close(-273.15)),
    _rt("rt_complex", complex(1, 2), _simple(complex(1, 2))),
    _rt("rt_string", "hello, 世界", _simple("hello, 世界")),
    _rt("rt_string_empty", "", _simple("")),
    _rt("rt_bytes", b"hello", _simple(b"hello")),
    _rt("rt_bytes_empty", b"", _simple(b"")),
    # --- edge cases: very large integers ---
    _rt("rt_int_very_large", 1 << 100, _simple(1 << 100)),
    _rt("rt_int_very_negative", -(1 << 100), _simple(-(1 << 100))),
    # --- edge cases: Unicode strings ---
    _rt("rt_string_unicode", "日本語テスト 🎉", _simple("日本語テスト 🎉")),
    _rt("rt_string_null_bytes", "abc\x00def", _simple("abc\x00def")),
    # --- structs via Schema ---
    _rt(
        "rt_struct_simple",
        {"X": 22, "Y": 33},
        lambda d: (
            isinstance(d, GobStruct) and d.gob_type == "Point"
            and d["X"] == 22 and d["Y"] == 33
        ) or pytest.fail(f"unexpected: {d!r}"),
        schema=_POINT_SCHEMA,
    ),
    _rt(
        "rt_struct_zero_fields",
        {"Name": "Bob", "Value": 0, "Extra": 0.0},
        lambda d: (
            isinstance(d, GobStruct) and d.gob_type == "PartialStruct"
            and d["Name"] == "Bob" and d["Value"] == 0 and d["Extra"] == 0.0
        ) or pytest.fail(f"unexpected: {d!r}"),
        schema=_PARTIAL_SCHEMA,
    ),
    # --- slices ---
    _rt("rt_slice_int", [1, 2, 3], _simple([1, 2, 3])),
    _rt("rt_slice_string", ["a", "b", "c"], _simple(["a", "b", "c"])),
    # Empty collections tested separately (require explicit elem_type/key_type)
]


@pytest.mark.parametrize("value,encode_kwargs,assert_fn", ROUND_TRIP_CASES)
def test_round_trip(value, encode_kwargs, assert_fn) -> None:
    """Encode a Python value, decode it back, and verify the result."""
    gob_bytes = pygob.encode(value, **encode_kwargs)
    decoded = pygob.decode(gob_bytes)
    assert_fn(decoded)


def test_round_trip_struct_mixed() -> None:
    """Round-trip a struct with mixed field types."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"Name": "Alice", "Age": 30, "Score": 9.5, "Active": True}, schema=_MIXED_SCHEMA)

    buf.seek(0)
    dec = Decoder(buf)
    result = dec.decode()

    assert isinstance(result, GobStruct)
    assert result.gob_type == "MixedStruct"
    assert result["Name"] == "Alice"
    assert result["Age"] == 30
    assert math.isclose(result["Score"], 9.5)
    assert result["Active"] is True


def test_round_trip_nested_struct() -> None:
    """Round-trip a nested struct (NestedStruct contains a Point field)."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode(
        {"Label": "test", "Origin": {"X": 1, "Y": 2}},
        schema=_OUTER_SCHEMA,
    )

    buf.seek(0)
    dec = Decoder(buf)
    result = dec.decode()

    assert isinstance(result, GobStruct)
    assert result.gob_type == "NestedStruct"
    assert result["Label"] == "test"
    origin = result["Origin"]
    assert isinstance(origin, GobStruct)
    assert origin["X"] == 1
    assert origin["Y"] == 2


def test_round_trip_slice_of_structs() -> None:
    """Round-trip a slice of GobStructs."""
    point_schema = Schema("Point", X=GOB_INT, Y=GOB_INT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode([{"X": 1, "Y": 2}, {"X": 3, "Y": 4}], elem_type=point_schema)

    buf.seek(0)
    dec = Decoder(buf)
    result = dec.decode()

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["X"] == 1
    assert result[1]["X"] == 3


def test_round_trip_map_string_int() -> None:
    """Round-trip a map[string]int."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"one": 1, "two": 2})

    buf.seek(0)
    dec = Decoder(buf)
    result = dec.decode()

    assert isinstance(result, dict)
    assert result == {"one": 1, "two": 2}


def test_round_trip_multi_message() -> None:
    """Two values encoded by the same Encoder share the type definition."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"X": 1, "Y": 2}, schema=_POINT_SCHEMA)
    enc.encode({"X": 3, "Y": 4}, schema=_POINT_SCHEMA)

    buf.seek(0)
    dec = Decoder(buf)
    r1 = dec.decode()
    r2 = dec.decode()

    assert r1["X"] == 1 and r1["Y"] == 2
    assert r2["X"] == 3 and r2["Y"] == 4


def test_round_trip_gobstruct_carries_schema() -> None:
    """A GobStruct decoded from gob bytes can be re-encoded without an external schema."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"X": 7, "Y": 8}, schema=_POINT_SCHEMA)

    buf.seek(0)
    decoded = Decoder(buf).decode()
    assert isinstance(decoded, GobStruct)

    buf2 = io.BytesIO()
    Encoder(buf2).encode(decoded)

    buf2.seek(0)
    re_decoded = Decoder(buf2).decode()
    assert re_decoded["X"] == 7
    assert re_decoded["Y"] == 8


# ---------------------------------------------------------------------------
# 3. Byte-level comparison for deterministic cases
# ---------------------------------------------------------------------------


def _load_gob(name: str) -> bytes:
    return (TESTDATA / f"{name}.gob").read_bytes()


def _encode_scalar(value) -> bytes:
    buf = io.BytesIO()
    Encoder(buf).encode(value)
    return buf.getvalue()


@pytest.mark.parametrize("name,value", [
    ("scalar_bool_true", True),
    ("scalar_bool_false", False),
    ("scalar_int_zero", 0),
    ("scalar_int_positive", 42),
    ("scalar_int_negative", -42),
    ("scalar_int_large", 1 << 60),
    ("scalar_uint", UInt(42)),
    ("scalar_uint_large", UInt(1 << 63)),
    ("scalar_float", 3.14159),
    ("scalar_float_zero", 0.0),
    ("scalar_float_negative", -273.15),
    ("scalar_complex", complex(1, 2)),
    ("scalar_string", "hello, 世界"),
    ("scalar_string_empty", ""),
    ("scalar_bytes", b"hello"),
])
def test_byte_level_scalar(name: str, value) -> None:
    """Encoded Python scalar bytes must exactly match Go-generated .gob file."""
    expected = _load_gob(name)
    actual = _encode_scalar(value)
    assert actual == expected, (
        f"{name}: bytes mismatch\n"
        f"  expected: {expected.hex()}\n"
        f"  actual:   {actual.hex()}"
    )




# ---------------------------------------------------------------------------
# 4. Edge cases
# ---------------------------------------------------------------------------


def test_edge_empty_slice() -> None:
    """Empty slice encodes and decodes correctly (elem_type required)."""
    buf = io.BytesIO()
    Encoder(buf).encode([], elem_type=GOB_INT)
    buf.seek(0)
    assert Decoder(buf).decode() == []


def test_edge_empty_map() -> None:
    """Empty map encodes and decodes correctly (key_type/elem_type required)."""
    buf = io.BytesIO()
    Encoder(buf).encode({}, key_type=GOB_STRING, elem_type=GOB_INT)
    buf.seek(0)
    assert Decoder(buf).decode() == {}


def test_edge_zero_valued_struct_fields() -> None:
    """A struct where all fields are zero round-trips correctly."""
    schema = Schema("Point", X=GOB_INT, Y=GOB_INT)
    buf = io.BytesIO()
    Encoder(buf).encode({"X": 0, "Y": 0}, schema=schema)
    buf.seek(0)
    result = Decoder(buf).decode()
    assert result["X"] == 0
    assert result["Y"] == 0


def test_edge_very_large_integer() -> None:
    """Integers larger than 2**64 encode and decode correctly."""
    huge = 2**200 + 12345
    assert pygob.decode(pygob.encode(huge)) == huge


def test_edge_very_negative_integer() -> None:
    """Very negative integers encode and decode correctly."""
    huge_neg = -(2**200 + 99999)
    assert pygob.decode(pygob.encode(huge_neg)) == huge_neg


def test_edge_unicode_string() -> None:
    """Multi-byte Unicode strings encode and decode correctly."""
    s = "こんにちは world 🌍 — ñoño"
    assert pygob.decode(pygob.encode(s)) == s


def test_edge_empty_string() -> None:
    """Empty string encodes and decodes correctly."""
    assert pygob.decode(pygob.encode("")) == ""


def test_edge_empty_bytes() -> None:
    """Empty bytes value encodes and decodes correctly."""
    assert pygob.decode(pygob.encode(b"")) == b""


def test_edge_float_special_values() -> None:
    """inf and -inf survive a round-trip."""
    for val in (math.inf, -math.inf):
        result = pygob.decode(pygob.encode(val))
        assert result == val


def test_edge_complex_zero() -> None:
    """complex(0, 0) encodes and decodes correctly."""
    assert pygob.decode(pygob.encode(complex(0, 0))) == complex(0, 0)


def test_edge_slice_of_large_ints() -> None:
    """A slice of large integers encodes and decodes correctly."""
    values = [1 << 60, -(1 << 60), 0, 1, -1]
    result = pygob.decode(pygob.encode(values))
    assert result == values


def test_edge_map_string_bool() -> None:
    """A map[string]bool (inferred types) round-trips correctly."""
    m = {"yes": True, "no": False}
    result = pygob.decode(pygob.encode(m))
    assert result == m
