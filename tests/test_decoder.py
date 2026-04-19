"""Tests for pygob/decoder.py — message framing and type-definition handling."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from pygob.decoder import Decoder
from pygob.types import GobStruct
from pygob.wire import INT, BOOL, UINT, FLOAT, BYTES, STRING, COMPLEX, INTERFACE

TESTDATA = Path(__file__).parent / "testdata"


def _load_gob(name: str) -> bytes:
    return (TESTDATA / f"{name}.gob").read_bytes()


# ---------------------------------------------------------------------------
# Bootstrap registry
# ---------------------------------------------------------------------------


def test_decoder_bootstrap_registry_contains_primitive_ids():
    """The type registry is pre-populated with all bootstrap type IDs."""
    import io

    dec = Decoder(io.BytesIO(b""))
    for tid in (BOOL, INT, UINT, FLOAT, BYTES, STRING, COMPLEX, INTERFACE):
        assert tid in dec._type_registry, f"bootstrap type {tid} missing from registry"


# ---------------------------------------------------------------------------
# _read_message + _process_type_definition using the real struct_simple.gob
# ---------------------------------------------------------------------------


def test_read_message_type_definition():
    """_read_message returns a negative type_id for a type-definition message."""
    import io

    data = _load_gob("struct_simple")
    dec = Decoder(io.BytesIO(data))

    type_id, payload = dec._read_message()

    # Type definitions always have a negative type_id in the stream.
    assert type_id < 0, f"expected negative type_id for a type definition, got {type_id}"
    assert len(payload) > 0


def test_process_type_definition_point_struct():
    """Decoding the Point type definition registers a StructWireType with X and Y fields."""
    import io

    data = _load_gob("struct_simple")
    dec = Decoder(io.BytesIO(data))

    type_id, payload = dec._read_message()
    # type_id is negative for a type definition; the actual ID is its negation.
    actual_id = -type_id
    dec._process_type_definition(actual_id, payload)

    assert actual_id in dec._type_registry
    wt = dec._type_registry[actual_id]
    assert wt is not None
    assert wt.struct_t is not None, "expected a StructWireType"
    assert wt.struct_t.common.name == "Point"
    assert wt.struct_t.common.id == actual_id

    fields = wt.struct_t.fields
    assert len(fields) == 2
    assert fields[0].name == "X"
    assert fields[0].id == INT
    assert fields[1].name == "Y"
    assert fields[1].id == INT


def test_read_message_value_after_type_definition():
    """After the type definition, _read_message returns a positive type_id for the value."""
    import io

    data = _load_gob("struct_simple")
    dec = Decoder(io.BytesIO(data))

    # First message: type definition
    type_id, payload = dec._read_message()
    actual_id = -type_id
    dec._process_type_definition(actual_id, payload)

    # Second message: value
    value_type_id, value_payload = dec._read_message()
    assert value_type_id > 0, f"expected positive type_id for a value message, got {value_type_id}"
    assert value_type_id == actual_id
    assert len(value_payload) > 0


# ---------------------------------------------------------------------------
# Task 4.3 — decode(): scalar bootstrap types
# ---------------------------------------------------------------------------

import base64
import io as _io
import math


def _decode_gob(name: str):
    """Convenience: load a .gob file and return the decoded Python value."""
    data = _load_gob(name)
    return Decoder(_io.BytesIO(data)).decode()


def test_decode_scalar_bool_true():
    assert _decode_gob("scalar_bool_true") is True


def test_decode_scalar_bool_false():
    assert _decode_gob("scalar_bool_false") is False


def test_decode_scalar_int_zero():
    result = _decode_gob("scalar_int_zero")
    assert result == 0
    assert isinstance(result, int)


def test_decode_scalar_int_positive():
    assert _decode_gob("scalar_int_positive") == 42


def test_decode_scalar_int_negative():
    assert _decode_gob("scalar_int_negative") == -42


def test_decode_scalar_int_large():
    assert _decode_gob("scalar_int_large") == 1 << 60


def test_decode_scalar_uint():
    assert _decode_gob("scalar_uint") == 42


def test_decode_scalar_uint_large():
    assert _decode_gob("scalar_uint_large") == 1 << 63


def test_decode_scalar_float():
    result = _decode_gob("scalar_float")
    assert math.isclose(result, 3.14159, rel_tol=1e-9)


def test_decode_scalar_float_zero():
    result = _decode_gob("scalar_float_zero")
    assert result == 0.0
    assert isinstance(result, float)


def test_decode_scalar_float_negative():
    result = _decode_gob("scalar_float_negative")
    assert math.isclose(result, -273.15, rel_tol=1e-9)


def test_decode_scalar_complex():
    result = _decode_gob("scalar_complex")
    assert result == complex(1, 2)


def test_decode_scalar_string():
    assert _decode_gob("scalar_string") == "hello, 世界"


def test_decode_scalar_string_empty():
    assert _decode_gob("scalar_string_empty") == ""


def test_decode_scalar_bytes():
    result = _decode_gob("scalar_bytes")
    assert result == b"hello"
    assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# Task 4.4 — decode(): struct types
# ---------------------------------------------------------------------------


def test_decode_struct_simple():
    result = _decode_gob("struct_simple")
    assert isinstance(result, GobStruct)
    assert result.gob_type == "Point"
    assert result["X"] == 22
    assert result["Y"] == 33
    # Attribute access works too
    assert result.X == 22
    assert result.Y == 33


def test_decode_struct_simple_schema():
    result = _decode_gob("struct_simple")
    schema = result.gob_schema
    assert schema.name == "Point"
    assert schema.fields["X"] == INT
    assert schema.fields["Y"] == INT


def test_decode_struct_mixed():
    result = _decode_gob("struct_mixed")
    assert isinstance(result, GobStruct)
    assert result.gob_type == "MixedStruct"
    assert result["Name"] == "Alice"
    assert result["Age"] == 30
    assert math.isclose(result["Score"], 9.5, rel_tol=1e-9)
    assert result["Active"] is True


def test_decode_struct_mixed_schema():
    result = _decode_gob("struct_mixed")
    schema = result.gob_schema
    assert schema.name == "MixedStruct"
    assert schema.fields["Name"] == STRING
    assert schema.fields["Age"] == INT
    assert schema.fields["Score"] == FLOAT
    assert schema.fields["Active"] == BOOL


def test_decode_struct_zero_fields():
    """Fields omitted in the stream because they are zero should get zero values."""
    result = _decode_gob("struct_zero_fields")
    assert isinstance(result, GobStruct)
    assert result.gob_type == "PartialStruct"
    assert result["Name"] == "Bob"
    assert result["Value"] == 0
    assert result["Extra"] == 0.0


def test_decode_struct_as_dict():
    result = _decode_gob("struct_simple")
    d = dict(result)
    assert d == {"X": 22, "Y": 33}


def test_decode_struct_equality():
    result = _decode_gob("struct_simple")
    assert result == {"X": 22, "Y": 33}


# ---------------------------------------------------------------------------
# Task 4.5 — decode(): slices, arrays, maps
# ---------------------------------------------------------------------------


def test_decode_slice_int():
    result = _decode_gob("slice_int")
    assert result == [1, 2, 3]
    assert isinstance(result, list)


def test_decode_slice_string():
    result = _decode_gob("slice_string")
    assert result == ["a", "b", "c"]


def test_decode_slice_empty():
    result = _decode_gob("slice_empty")
    assert result == []
    assert isinstance(result, list)


def test_decode_array_int():
    result = _decode_gob("array_int")
    assert result == [10, 20, 30]
    assert isinstance(result, list)


def test_decode_map_string_int():
    result = _decode_gob("map_string_int")
    assert isinstance(result, dict)
    assert result == {"one": 1, "two": 2}


def test_decode_map_int_string():
    result = _decode_gob("map_int_string")
    assert isinstance(result, dict)
    assert result == {1: "one", 2: "two"}


def test_decode_map_empty():
    result = _decode_gob("map_empty")
    assert isinstance(result, dict)
    assert result == {}


def test_decode_nested_slice_of_structs():
    result = _decode_gob("nested_slice_of_structs")
    assert isinstance(result, list)
    assert len(result) == 2
    assert isinstance(result[0], GobStruct)
    assert result[0].gob_type == "Point"
    assert result[0]["X"] == 1
    assert result[0]["Y"] == 2
    assert result[1]["X"] == 3
    assert result[1]["Y"] == 4


def test_decode_nested_map_of_structs():
    result = _decode_gob("nested_map_of_structs")
    assert isinstance(result, dict)
    assert "a" in result
    point = result["a"]
    assert isinstance(point, GobStruct)
    assert point.gob_type == "Point"
    assert point["X"] == 1
    assert point["Y"] == 2


# ---------------------------------------------------------------------------
# Task 4.6 — decode(): nested and complex types
# ---------------------------------------------------------------------------


def test_decode_struct_nested():
    """NestedStruct has an Origin field that is itself a Point struct."""
    result = _decode_gob("struct_nested")
    assert isinstance(result, GobStruct)
    assert result.gob_type == "NestedStruct"
    assert result["Label"] == "test"
    origin = result["Origin"]
    assert isinstance(origin, GobStruct)
    assert origin.gob_type == "Point"
    assert origin["X"] == 1
    assert origin["Y"] == 2


def test_decode_struct_nested_schema():
    """The schema for a nested struct field should be a nested Schema, not a bare int."""
    result = _decode_gob("struct_nested")
    schema = result.gob_schema
    assert schema.name == "NestedStruct"
    assert schema.fields["Label"] == STRING
    origin_schema = schema.fields["Origin"]
    assert hasattr(origin_schema, "name"), "Origin field schema should be a Schema object"
    assert origin_schema.name == "Point"


def test_decode_multi_message():
    """A multi-message stream reuses the type definition for both values."""
    import io

    data = _load_gob("multi_message")
    dec = Decoder(io.BytesIO(data))

    result1 = dec.decode()
    result2 = dec.decode()

    assert isinstance(result1, GobStruct)
    assert result1.gob_type == "Point"
    assert result1["X"] == 1
    assert result1["Y"] == 2

    assert isinstance(result2, GobStruct)
    assert result2.gob_type == "Point"
    assert result2["X"] == 3
    assert result2["Y"] == 4


def test_decode_multi_message_type_reuse():
    """The second message in a multi-message stream requires no new type definitions."""
    import io

    data = _load_gob("multi_message")
    dec = Decoder(io.BytesIO(data))

    # Decode first message — installs the Point type definition
    dec.decode()
    registry_size_after_first = len(dec._type_registry)

    # Decode second message — should NOT add new entries to the registry
    dec.decode()
    registry_size_after_second = len(dec._type_registry)

    assert registry_size_after_first == registry_size_after_second, (
        "Second message should reuse the existing type definition, not add new ones"
    )


# ---------------------------------------------------------------------------
# Task 4.7 — decode(): interface values
# ---------------------------------------------------------------------------


def test_decode_interface_value():
    """Container.Value holds a Point{1,2} via interface{}; should decode to GobStruct."""
    result = _decode_gob("interface_value")
    assert isinstance(result, GobStruct)
    assert result.gob_type == "Container"
    assert result["Name"] == "test"
    value = result["Value"]
    assert isinstance(value, GobStruct)
    assert value.gob_type == "Point"
    assert value["X"] == 1
    assert value["Y"] == 2


def test_decode_interface_value_concrete_attribute_access():
    """Attribute access works on the interface concrete value."""
    result = _decode_gob("interface_value")
    point = result.Value
    assert point.X == 1
    assert point.Y == 2


def test_decode_interface_value_schema():
    """Container's schema marks the Value field as interface type."""
    result = _decode_gob("interface_value")
    schema = result.gob_schema
    assert schema.name == "Container"
    assert schema.fields["Name"] == STRING
    assert schema.fields["Value"] == INTERFACE


def test_decode_interface_value_registers_concrete_type():
    """Inline type def for Point is registered in the decoder's type registry."""
    import io

    data = _load_gob("interface_value")
    dec = Decoder(io.BytesIO(data))
    dec.decode()
    # The inline type def for Point (type 64) should now be in the registry.
    point_wt = next(
        (wt for wt in dec._type_registry.values() if wt and wt.struct_t and wt.struct_t.common.name == "Point"),
        None,
    )
    assert point_wt is not None, "Point type def should have been registered"
    assert point_wt.struct_t.common.name == "Point"


def test_decode_interface_no_register_required():
    """Go→Python interface decoding does NOT require dec.register().

    Inline type definitions in the gob stream are self-describing.
    register() is only needed for Python→Python re-encoding of interface fields.
    """
    import io

    data = _load_gob("interface_value")
    dec = Decoder(io.BytesIO(data))
    # Intentionally NOT calling dec.register()
    result = dec.decode()
    assert isinstance(result, GobStruct)
    assert result.Value.gob_type == "Point"
    assert result.Value.X == 1
    assert result.Value.Y == 2


def test_decoder_register_method():
    """register() stores a name→schema mapping without error."""
    import io
    from pygob.types import Schema

    dec = Decoder(io.BytesIO(b""))
    schema = Schema("MyType", X=INT)
    dec.register("main.MyType", schema)
    assert dec._name_registry["main.MyType"] is schema


# ---------------------------------------------------------------------------
# Task 4.8 — decode(): GobEncoder / BinaryMarshaler types
# ---------------------------------------------------------------------------


def test_decode_gob_encoded_type():
    """time.Time (GobEncoder) decodes to GobEncoded with the wire type name and raw bytes."""
    from pygob.types import GobEncoded

    result = _decode_gob("scalar_time")
    assert isinstance(result, GobEncoded)
    assert result.type_name == "Time"
    assert isinstance(result.data, bytes)
    assert len(result.data) > 0


def test_decode_gob_encoded_data_length():
    """time.Time MarshalBinary produces exactly 15 bytes (version + sec + nsec + offset)."""
    from pygob.types import GobEncoded

    result = _decode_gob("scalar_time")
    assert isinstance(result, GobEncoded)
    assert len(result.data) == 15


def test_register_codec_custom_decoder():
    """A registered codec is called instead of returning GobEncoded."""
    import io
    import struct
    import datetime

    def decode_time(data: bytes) -> datetime.datetime:
        version = data[0]
        assert version == 1
        sec_since_y1 = struct.unpack(">q", data[1:9])[0]
        nsec = struct.unpack(">i", data[9:13])[0]
        offset_min = struct.unpack(">h", data[13:15])[0]
        UNIX_EPOCH_OFFSET = 62135596800
        unix_sec = sec_since_y1 - UNIX_EPOCH_OFFSET
        if offset_min == -1:
            tz = datetime.timezone.utc
        else:
            tz = datetime.timezone(datetime.timedelta(minutes=offset_min))
        epoch = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        return (epoch + datetime.timedelta(seconds=unix_sec, microseconds=nsec // 1000)).astimezone(tz)

    data = _load_gob("scalar_time")
    dec = Decoder(io.BytesIO(data))
    dec.register_codec("Time", decode_time)
    result = dec.decode()

    assert isinstance(result, datetime.datetime)
    expected = datetime.datetime(2009, 11, 10, 23, 0, 0, tzinfo=datetime.timezone.utc)
    assert result == expected


def test_register_codec_method_exists():
    """register_codec() stores the decode function without error."""
    import io

    dec = Decoder(io.BytesIO(b""))
    fn = lambda data: data
    dec.register_codec("SomeType", fn)
    assert dec._codec_registry["SomeType"] is fn


def test_gob_encoded_without_codec_has_correct_unix_time():
    """Verify the raw bytes in GobEncoded decode to the expected Unix timestamp."""
    import struct
    from pygob.types import GobEncoded

    result = _decode_gob("scalar_time")
    assert isinstance(result, GobEncoded)
    data = result.data
    sec_since_y1 = struct.unpack(">q", data[1:9])[0]
    UNIX_EPOCH_OFFSET = 62135596800
    unix_sec = sec_since_y1 - UNIX_EPOCH_OFFSET
    assert unix_sec == 1257894000  # 2009-11-10 23:00:00 UTC
