"""Cross-validation tests: Python Encoder output verified by Go's gob decoder.

Each test encodes a value using pygob's Encoder, pipes the bytes to
``go run ./tests/go_verify <test_name>``, and asserts that Go can successfully
decode the result and the values match.

Tests are skipped (not failed) when Go is not available on PATH.
"""

from __future__ import annotations

import base64
import io

import pytest

from pygob.encoder import Encoder
from pygob.types import GobStruct, Schema, UInt
from pygob.wire import BOOL, BYTES, COMPLEX, FLOAT, INT, INTERFACE, STRING, UINT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode(value, **kwargs) -> bytes:
    """Encode *value* with optional keyword args; return raw bytes."""
    buf = io.BytesIO()
    Encoder(buf).encode(value, **kwargs)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Scalars: bool
# ---------------------------------------------------------------------------


def test_go_verify_scalar_bool_true(go_verify):
    result = go_verify("scalar_bool_true", _encode(True))
    assert result["ok"] is True
    assert result["value"] is True


def test_go_verify_scalar_bool_false(go_verify):
    result = go_verify("scalar_bool_false", _encode(False))
    assert result["ok"] is True
    assert result["value"] is False


# ---------------------------------------------------------------------------
# Scalars: signed int
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,name", [
    (0, "scalar_int_zero"),
    (42, "scalar_int_positive"),
    (-42, "scalar_int_negative"),
    (1 << 60, "scalar_int_large"),
])
def test_go_verify_scalar_int(go_verify, value, name):
    result = go_verify(name, _encode(value))
    assert result["ok"] is True
    assert result["value"] == value


# ---------------------------------------------------------------------------
# Scalars: unsigned int
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,name", [
    (42, "scalar_uint"),
    (1 << 63, "scalar_uint_large"),
])
def test_go_verify_scalar_uint(go_verify, value, name):
    result = go_verify(name, _encode(UInt(value)))
    assert result["ok"] is True
    assert int(result["value"]) == value


# ---------------------------------------------------------------------------
# Scalars: float
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,name", [
    (3.14159, "scalar_float"),
    (0.0, "scalar_float_zero"),
    (-273.15, "scalar_float_negative"),
])
def test_go_verify_scalar_float(go_verify, value, name):
    result = go_verify(name, _encode(value))
    assert result["ok"] is True
    assert result["value"] == pytest.approx(value)


# ---------------------------------------------------------------------------
# Scalars: complex
# ---------------------------------------------------------------------------


def test_go_verify_scalar_complex(go_verify):
    result = go_verify("scalar_complex", _encode(1 + 2j))
    assert result["ok"] is True
    assert result["value"]["real"] == pytest.approx(1.0)
    assert result["value"]["imag"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Scalars: string
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,name", [
    ("hello, 世界", "scalar_string"),
    ("", "scalar_string_empty"),
])
def test_go_verify_scalar_string(go_verify, value, name):
    result = go_verify(name, _encode(value))
    assert result["ok"] is True
    assert result["value"] == value


# ---------------------------------------------------------------------------
# Scalars: bytes
# ---------------------------------------------------------------------------


def test_go_verify_scalar_bytes(go_verify):
    result = go_verify("scalar_bytes", _encode(b"hello"))
    assert result["ok"] is True
    # encoding/json marshals []byte as standard base64
    assert base64.b64decode(result["value"]) == b"hello"


# ---------------------------------------------------------------------------
# Structs
# ---------------------------------------------------------------------------


def test_go_verify_struct_simple(go_verify):
    """Python-encoded Point{X:22, Y:33} is decoded correctly by Go."""
    point_schema = Schema("Point", X=INT, Y=INT)
    result = go_verify("struct_simple", _encode({"X": 22, "Y": 33}, schema=point_schema))
    assert result["ok"] is True
    assert result["value"]["X"] == 22
    assert result["value"]["Y"] == 33


def test_go_verify_struct_mixed(go_verify):
    """Python-encoded MixedStruct is decoded correctly by Go."""
    mixed_schema = Schema("MixedStruct", Name=STRING, Age=INT, Score=FLOAT, Active=BOOL)
    data = _encode({"Name": "Alice", "Age": 30, "Score": 9.5, "Active": True}, schema=mixed_schema)
    result = go_verify("struct_mixed", data)
    assert result["ok"] is True
    assert result["value"]["Name"] == "Alice"
    assert result["value"]["Age"] == 30
    assert result["value"]["Score"] == pytest.approx(9.5)
    assert result["value"]["Active"] is True


def test_go_verify_struct_nested(go_verify):
    """Python-encoded NestedStruct{Label:'test', Origin:Point{1,2}} is decoded correctly by Go."""
    point_schema = Schema("Point", X=INT, Y=INT)
    nested_schema = Schema("NestedStruct", Label=STRING, Origin=point_schema)
    data = _encode({"Label": "test", "Origin": {"X": 1, "Y": 2}}, schema=nested_schema)
    result = go_verify("struct_nested", data)
    assert result["ok"] is True
    assert result["value"]["Label"] == "test"
    assert result["value"]["Origin"]["X"] == 1
    assert result["value"]["Origin"]["Y"] == 2


def test_go_verify_struct_zero_fields(go_verify):
    """Python-encoded PartialStruct{Name:'Bob'} with zero fields omitted is decoded correctly."""
    partial_schema = Schema("PartialStruct", Name=STRING, Value=INT, Extra=FLOAT)
    data = _encode({"Name": "Bob", "Value": 0, "Extra": 0.0}, schema=partial_schema)
    result = go_verify("struct_zero_fields", data)
    assert result["ok"] is True
    assert result["value"]["Name"] == "Bob"
    assert result["value"]["Value"] == 0
    assert result["value"]["Extra"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Slices
# ---------------------------------------------------------------------------


def test_go_verify_slice_int(go_verify):
    result = go_verify("slice_int", _encode([1, 2, 3]))
    assert result["ok"] is True
    assert result["value"] == [1, 2, 3]


def test_go_verify_slice_string(go_verify):
    result = go_verify("slice_string", _encode(["a", "b", "c"]))
    assert result["ok"] is True
    assert result["value"] == ["a", "b", "c"]


def test_go_verify_slice_empty(go_verify):
    result = go_verify("slice_empty", _encode([], elem_type=INT))
    assert result["ok"] is True
    assert result["value"] == []


# ---------------------------------------------------------------------------
# Arrays
# ---------------------------------------------------------------------------


def test_go_verify_array_int(go_verify):
    """Python-encoded [3]int array is decoded correctly by Go."""
    result = go_verify("array_int", _encode([10, 20, 30], array_length=3))
    assert result["ok"] is True
    assert list(result["value"]) == [10, 20, 30]


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------


def test_go_verify_map_string_int(go_verify):
    result = go_verify("map_string_int", _encode({"one": 1, "two": 2}))
    assert result["ok"] is True
    assert result["value"] == {"one": 1, "two": 2}


def test_go_verify_map_int_string(go_verify):
    result = go_verify("map_int_string", _encode({1: "one", 2: "two"}))
    assert result["ok"] is True
    # Go's JSON marshaling converts int map keys to strings
    assert result["value"] == {"1": "one", "2": "two"}


def test_go_verify_map_empty(go_verify):
    result = go_verify("map_empty", _encode({}, key_type=STRING, elem_type=INT))
    assert result["ok"] is True
    assert result["value"] == {}


# ---------------------------------------------------------------------------
# Nested composites
# ---------------------------------------------------------------------------


def test_go_verify_nested_slice_of_structs(go_verify):
    """Python-encoded []Point{{1,2},{3,4}} is decoded correctly by Go."""
    point_schema = Schema("Point", X=INT, Y=INT)
    items = [
        GobStruct("Point", point_schema, X=1, Y=2),
        GobStruct("Point", point_schema, X=3, Y=4),
    ]
    result = go_verify("nested_slice_of_structs", _encode(items))
    assert result["ok"] is True
    assert len(result["value"]) == 2
    assert result["value"][0] == {"X": 1, "Y": 2}
    assert result["value"][1] == {"X": 3, "Y": 4}


def test_go_verify_nested_map_of_structs(go_verify):
    """Python-encoded map[string]Point is decoded correctly by Go."""
    point_schema = Schema("Point", X=INT, Y=INT)
    value = {"a": GobStruct("Point", point_schema, X=1, Y=2)}
    result = go_verify("nested_map_of_structs", _encode(value))
    assert result["ok"] is True
    assert result["value"] == {"a": {"X": 1, "Y": 2}}


# ---------------------------------------------------------------------------
# Multi-message stream
# ---------------------------------------------------------------------------


def test_go_verify_multi_message(go_verify):
    """Two Point values encoded with the same Encoder are both decoded correctly by Go."""
    point_schema = Schema("Point", X=INT, Y=INT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"X": 1, "Y": 2}, schema=point_schema)
    enc.encode({"X": 3, "Y": 4}, schema=point_schema)

    result = go_verify("multi_message", buf.getvalue())
    assert result["ok"] is True
    assert len(result["value"]) == 2
    assert result["value"][0] == {"X": 1, "Y": 2}
    assert result["value"][1] == {"X": 3, "Y": 4}


# ---------------------------------------------------------------------------
# Interface values
# ---------------------------------------------------------------------------


def test_go_verify_time_codec(go_verify):
    """Python-encoded datetime (via TimeCodec) is decoded correctly by Go as time.Time."""
    from datetime import datetime, timezone
    import pygob
    from pygob.codecs import DEFAULT_CODECS

    dt = datetime(2009, 11, 10, 23, 0, 0, tzinfo=timezone.utc)
    buf = io.BytesIO()
    enc = pygob.Encoder(buf, codecs=DEFAULT_CODECS)
    enc.encode_gob_encoded(dt, "Time")

    result = go_verify("scalar_time", buf.getvalue())
    assert result["ok"] is True
    assert result["value"]["unix"] == 1257894000


def test_go_verify_uuid_codec(go_verify):
    """Python-encoded uuid.UUID (via UUIDCodec) is decoded correctly by Go."""
    import uuid
    import pygob
    from pygob.codecs import DEFAULT_CODECS

    test_uuid = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    buf = io.BytesIO()
    enc = pygob.Encoder(buf, codecs=DEFAULT_CODECS)
    enc.encode_gob_encoded(test_uuid, "UUID")

    result = go_verify("scalar_uuid", buf.getvalue())
    assert result["ok"] is True
    assert result["value"] == str(test_uuid)


# ---------------------------------------------------------------------------
# Interface values
# ---------------------------------------------------------------------------


def test_go_verify_struct_duration(go_verify):
    """Python-encoded EventDuration{Name:'request', Timeout:5s} is decoded correctly by Go."""
    from datetime import timedelta
    from pygob.types import GOB_DURATION

    event_schema = Schema("EventDuration", Name=STRING, Timeout=GOB_DURATION)
    data = _encode({"Name": "request", "Timeout": timedelta(seconds=5)}, schema=event_schema)

    result = go_verify("struct_duration", data)
    assert result["ok"] is True
    assert result["value"]["Name"] == "request"
    assert result["value"]["Timeout"] == 5_000_000_000  # 5s in nanoseconds


def test_go_verify_interface_value(go_verify):
    """Python-encoded Container{Name:'test', Value:Point{1,2}} is decoded correctly by Go."""
    point_schema = Schema("Point", X=INT, Y=INT)
    container_schema = Schema("Container", Name=STRING, Value=INTERFACE)

    point = GobStruct("Point", point_schema, X=1, Y=2)
    container = GobStruct("Container", container_schema, Name="test", Value=point)

    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.register("main.Point", point_schema)
    enc.encode(container)

    result = go_verify("interface_value", buf.getvalue())
    assert result["ok"] is True
    assert result["value"]["Name"] == "test"
    assert result["value"]["Value"]["X"] == 1
    assert result["value"]["Value"]["Y"] == 2
