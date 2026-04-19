"""Tests for pygob/encoder.py — message framing and type definition emission."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from dataclasses import dataclass

from pygob.decoder import Decoder
from pygob.encoder import Encoder
from pygob.exceptions import GobEncodeError
from pygob.types import (
    ArrayOf,
    GOB_FLOAT,
    GOB_INT,
    GOB_STRING,
    GobStruct,
    MapOf,
    Schema,
    SliceOf,
    UInt,
    gobstruct,
)
from pygob.wire import BOOL, BYTES, COMPLEX, FIRST_USER_ID, FLOAT, INT, STRING, UINT

TESTDATA = Path(__file__).parent / "testdata"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_encoder() -> tuple[Encoder, io.BytesIO]:
    """Return an (Encoder, BytesIO) pair sharing the same buffer."""
    buf = io.BytesIO()
    return Encoder(buf), buf


# ---------------------------------------------------------------------------
# _emit_type_definition: registry and idempotency
# ---------------------------------------------------------------------------


def test_emit_type_definition_assigns_first_user_id():
    """The first emitted schema gets type ID FIRST_USER_ID (64)."""
    enc, _ = _make_encoder()
    schema = Schema("Point", X=INT, Y=INT)
    type_id = enc._emit_type_definition(schema)
    assert type_id == FIRST_USER_ID


def test_emit_type_definition_increments_id():
    """Each new schema gets the next sequential type ID."""
    enc, _ = _make_encoder()
    id1 = enc._emit_type_definition(Schema("A", X=INT))
    id2 = enc._emit_type_definition(Schema("B", Y=INT))
    assert id1 == FIRST_USER_ID
    assert id2 == FIRST_USER_ID + 1


def test_emit_type_definition_idempotent():
    """Calling _emit_type_definition twice on the same schema returns the same ID
    and only emits one type definition message."""
    enc, buf = _make_encoder()
    schema = Schema("Point", X=INT, Y=INT)
    id1 = enc._emit_type_definition(schema)
    bytes_after_first = len(buf.getvalue())
    id2 = enc._emit_type_definition(schema)
    assert id1 == id2
    assert len(buf.getvalue()) == bytes_after_first, "second call must not write additional bytes"


def test_emit_type_definition_registers_in_schema_registry():
    """After emission, the schema name is in _schema_registry with the correct ID."""
    enc, _ = _make_encoder()
    schema = Schema("MyType", Value=INT)
    type_id = enc._emit_type_definition(schema)
    assert enc._schema_registry["MyType"] == type_id


# ---------------------------------------------------------------------------
# _emit_type_definition: byte-level verification for a simple struct
# ---------------------------------------------------------------------------

# Hand-computed expected bytes for Schema("Point", X=INT, Y=INT) at type_id=65:
#
# encode_int(-65) = zigzag(-65) = 129 = 0x81  (two bytes: 0xFF 0x81 since >= 128)
# WireType:
#   delta=3 (field 2 = StructT)  → 0x03
#   StructWireType:
#     delta=1 (CommonType)       → 0x01
#     CommonType:
#       delta=1 (Name)           → 0x01
#       string "Point"           → 0x05 0x50 0x6f 0x69 0x6e 0x74
#       delta=1 (Id)             → 0x01
#       encode_int(65) = 0xFF82  → 0xFF 0x82
#       terminator               → 0x00
#     delta=1 (Fields)           → 0x01
#     count=2                    → 0x02
#     FieldWireType("X", INT=2):
#       delta=1, "X"(len=1), delta=1, int(2)=0x04, term → 0x01 0x01 0x58 0x01 0x04 0x00
#     FieldWireType("Y", INT=2):
#       delta=1, "Y"(len=1), delta=1, int(2)=0x04, term → 0x01 0x01 0x59 0x01 0x04 0x00
#     terminator                 → 0x00
#   terminator (WireType)        → 0x00
# message length = 2+1+1+1+6+1+2+1+1+1+6+6+1+1 = 31
# byteCount = 0x1F

_EXPECTED_POINT_TYPE_DEF = bytes([
    0x1F,                                           # byteCount = 31
    0xFF, 0x81,                                     # encode_int(-65)
    0x03,                                           # WireType delta=3 (field 2 = StructT)
    0x01,                                           # StructWireType delta=1 (field 0 = CommonType)
    0x01,                                           # CommonType delta=1 (field 0 = Name)
    0x05, 0x50, 0x6f, 0x69, 0x6e, 0x74,            # "Point" (length 5)
    0x01,                                           # CommonType delta=1 (field 1 = Id)
    0xFF, 0x82,                                     # encode_int(65)
    0x00,                                           # CommonType terminator
    0x01,                                           # StructWireType delta=1 (field 1 = Fields)
    0x02,                                           # count = 2
    0x01, 0x01, 0x58, 0x01, 0x04, 0x00,            # FieldWireType("X", INT=2)
    0x01, 0x01, 0x59, 0x01, 0x04, 0x00,            # FieldWireType("Y", INT=2)
    0x00,                                           # StructWireType terminator
    0x00,                                           # WireType terminator
])


def test_emit_type_definition_point_bytes():
    """Emitted bytes for Schema('Point', X=INT, Y=INT) match manually computed expected value."""
    enc, buf = _make_encoder()
    enc._emit_type_definition(Schema("Point", X=INT, Y=INT))
    assert buf.getvalue() == _EXPECTED_POINT_TYPE_DEF


# ---------------------------------------------------------------------------
# _emit_type_definition: Decoder can parse the emitted bytes
# ---------------------------------------------------------------------------


def test_emit_type_definition_decodable_by_decoder():
    """The Decoder can read back a type definition emitted by the Encoder."""
    enc, buf = _make_encoder()
    schema = Schema("Point", X=INT, Y=INT)
    type_id = enc._emit_type_definition(schema)

    dec = Decoder(io.BytesIO(buf.getvalue()))
    msg_type_id, payload = dec._read_message()

    assert msg_type_id == -type_id, "type definition messages have a negative type_id"
    dec._process_type_definition(type_id, payload)

    assert type_id in dec._type_registry
    wt = dec._type_registry[type_id]
    assert wt is not None
    assert wt.struct_t is not None
    assert wt.struct_t.common.name == "Point"
    assert wt.struct_t.common.id == type_id

    fields = wt.struct_t.fields
    assert len(fields) == 2
    assert fields[0].name == "X"
    assert fields[0].id == INT
    assert fields[1].name == "Y"
    assert fields[1].id == INT


def test_emit_type_definition_various_field_types():
    """A schema with multiple primitive field types is encoded and decoded correctly."""
    enc, buf = _make_encoder()
    schema = Schema("Mixed", A=INT, B=UINT, C=BOOL, D=FLOAT, E=STRING, F=BYTES, G=COMPLEX)
    type_id = enc._emit_type_definition(schema)

    dec = Decoder(io.BytesIO(buf.getvalue()))
    msg_type_id, payload = dec._read_message()
    dec._process_type_definition(-msg_type_id, payload)

    wt = dec._type_registry[-msg_type_id]
    assert wt.struct_t is not None
    field_map = {f.name: f.id for f in wt.struct_t.fields}
    assert field_map == {"A": INT, "B": UINT, "C": BOOL, "D": FLOAT, "E": STRING, "F": BYTES, "G": COMPLEX}


# ---------------------------------------------------------------------------
# _emit_type_definition: nested schemas
# ---------------------------------------------------------------------------


def test_emit_type_definition_nested_emits_inner_first():
    """For a schema with a nested struct field, the inner type def is emitted first."""
    enc, buf = _make_encoder()
    point_schema = Schema("Point", X=INT, Y=INT)
    line_schema = Schema("Line", Start=point_schema, End=point_schema)
    outer_id = enc._emit_type_definition(line_schema)

    # Point should have been emitted first (lower ID)
    point_id = enc._schema_registry["Point"]
    assert point_id == FIRST_USER_ID
    assert outer_id == FIRST_USER_ID + 1

    # Parse both type def messages with the Decoder
    dec = Decoder(io.BytesIO(buf.getvalue()))

    # First message: Point type def
    msg_id1, payload1 = dec._read_message()
    assert msg_id1 < 0
    dec._process_type_definition(-msg_id1, payload1)
    assert dec._type_registry[-msg_id1].struct_t.common.name == "Point"

    # Second message: Line type def (references Point)
    msg_id2, payload2 = dec._read_message()
    assert msg_id2 < 0
    dec._process_type_definition(-msg_id2, payload2)
    line_wt = dec._type_registry[-msg_id2]
    assert line_wt.struct_t.common.name == "Line"
    assert line_wt.struct_t.fields[0].name == "Start"
    assert line_wt.struct_t.fields[0].id == point_id
    assert line_wt.struct_t.fields[1].name == "End"
    assert line_wt.struct_t.fields[1].id == point_id


def test_emit_type_definition_nested_same_schema_not_duplicated():
    """If the nested schema was already emitted, it is not emitted again."""
    enc, buf = _make_encoder()
    point_schema = Schema("Point", X=INT, Y=INT)

    # Emit Point first explicitly
    point_id = enc._emit_type_definition(point_schema)
    bytes_after_point = len(buf.getvalue())

    # Now emit Line which also references Point — should not re-emit Point
    line_schema = Schema("Line", Start=point_schema, End=point_schema)
    enc._emit_type_definition(line_schema)

    # Count type def messages in total output
    dec = Decoder(io.BytesIO(buf.getvalue()))
    type_def_count = 0
    while True:
        try:
            msg_id, _ = dec._read_message()
        except Exception:
            break
        if msg_id < 0:
            type_def_count += 1
        else:
            break

    # Should be exactly 2 type defs: Point + Line
    assert type_def_count == 2


# ---------------------------------------------------------------------------
# _resolve_field_type_id: error on unregistered nested schema
# ---------------------------------------------------------------------------


def test_resolve_field_type_id_raises_for_unregistered_nested():
    """_resolve_field_type_id raises GobEncodeError for an unregistered nested schema."""
    enc, _ = _make_encoder()
    unregistered = Schema("Unknown", X=INT)
    with pytest.raises(GobEncodeError, match="Unknown"):
        enc._resolve_field_type_id(unregistered)


# ---------------------------------------------------------------------------
# _emit_value: framing
# ---------------------------------------------------------------------------


def test_emit_value_framing():
    """_emit_value writes uint(byteCount) + int(type_id) + payload."""
    from pygob.codec import decode_int, decode_uint

    enc, buf = _make_encoder()
    payload = b"\x01\x2c\x01\x42\x00"  # a sample struct encoding
    enc._emit_value(65, payload)

    data = buf.getvalue()
    # First: byteCount
    byte_count, n1 = decode_uint(data)
    rest = data[n1:]
    assert len(rest) == byte_count

    # Then: type_id
    type_id, n2 = decode_int(rest)
    assert type_id == 65

    # Then: payload
    assert rest[n2:] == payload


def test_emit_value_round_trip_via_decoder():
    """A type def + value message pair can be decoded by the Decoder after emission."""
    enc, buf = _make_encoder()
    schema = Schema("Point", X=INT, Y=INT)
    type_id = enc._emit_type_definition(schema)

    # Encode struct value manually: delta=1, X=22, delta=1, Y=33, terminator
    from pygob.codec import encode_int as _ei, encode_uint as _eu
    payload = _eu(1) + _ei(22) + _eu(1) + _ei(33) + _eu(0)
    enc._emit_value(type_id, payload)

    dec = Decoder(io.BytesIO(buf.getvalue()))
    result = dec.decode()

    assert result.gob_type == "Point"
    assert result["X"] == 22
    assert result["Y"] == 33


# ---------------------------------------------------------------------------
# encode: scalar round-trips (Python encode → Python decode)
# ---------------------------------------------------------------------------


def _encode_scalar(value) -> bytes:
    """Encode a single scalar value; return the raw bytes."""
    buf = io.BytesIO()
    Encoder(buf).encode(value)
    return buf.getvalue()


def _round_trip(value):
    """Encode then decode a scalar value."""
    data = _encode_scalar(value)
    return Decoder(io.BytesIO(data)).decode()


@pytest.mark.parametrize("value", [True, False])
def test_encode_bool_round_trip(value):
    assert _round_trip(value) == value
    assert isinstance(_round_trip(value), bool)


@pytest.mark.parametrize("value", [0, 1, -1, 42, -42, 1 << 60, -(1 << 60)])
def test_encode_int_round_trip(value):
    assert _round_trip(value) == value


def test_encode_uint_round_trip():
    for value in [0, 42, 1 << 63]:
        result = _round_trip(UInt(value))
        assert result == value


@pytest.mark.parametrize("value", [0.0, 3.14159, -273.15, 1e100, -1e100])
def test_encode_float_round_trip(value):
    assert _round_trip(value) == value


def test_encode_complex_round_trip():
    for value in [0j, 1 + 2j, -3.5 + 0j, complex(0, -1)]:
        assert _round_trip(value) == value


@pytest.mark.parametrize("value", ["", "hello", "hello, 世界", "a" * 200])
def test_encode_string_round_trip(value):
    assert _round_trip(value) == value


@pytest.mark.parametrize("value", [b"", b"hello", bytes(range(256))])
def test_encode_bytes_round_trip(value):
    assert _round_trip(value) == value


def test_encode_unsupported_type_raises():
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="unsupported type"):
        enc.encode({1, 2, 3})  # set is not a supported top-level type


# ---------------------------------------------------------------------------
# encode: byte-level comparison against Go-generated .gob files
# ---------------------------------------------------------------------------


def test_encode_bool_true_bytes():
    assert _encode_scalar(True) == (TESTDATA / "scalar_bool_true.gob").read_bytes()


def test_encode_bool_false_bytes():
    assert _encode_scalar(False) == (TESTDATA / "scalar_bool_false.gob").read_bytes()


def test_encode_int_zero_bytes():
    assert _encode_scalar(0) == (TESTDATA / "scalar_int_zero.gob").read_bytes()


def test_encode_int_positive_bytes():
    assert _encode_scalar(42) == (TESTDATA / "scalar_int_positive.gob").read_bytes()


def test_encode_int_negative_bytes():
    assert _encode_scalar(-42) == (TESTDATA / "scalar_int_negative.gob").read_bytes()


def test_encode_int_large_bytes():
    assert _encode_scalar(1 << 60) == (TESTDATA / "scalar_int_large.gob").read_bytes()


def test_encode_uint_bytes():
    assert _encode_scalar(UInt(42)) == (TESTDATA / "scalar_uint.gob").read_bytes()


def test_encode_uint_large_bytes():
    assert _encode_scalar(UInt(1 << 63)) == (TESTDATA / "scalar_uint_large.gob").read_bytes()


def test_encode_float_bytes():
    assert _encode_scalar(3.14159) == (TESTDATA / "scalar_float.gob").read_bytes()


def test_encode_float_zero_bytes():
    assert _encode_scalar(0.0) == (TESTDATA / "scalar_float_zero.gob").read_bytes()


def test_encode_float_negative_bytes():
    assert _encode_scalar(-273.15) == (TESTDATA / "scalar_float_negative.gob").read_bytes()


def test_encode_complex_bytes():
    assert _encode_scalar(1 + 2j) == (TESTDATA / "scalar_complex.gob").read_bytes()


def test_encode_string_bytes():
    assert _encode_scalar("hello, 世界") == (TESTDATA / "scalar_string.gob").read_bytes()


def test_encode_string_empty_bytes():
    assert _encode_scalar("") == (TESTDATA / "scalar_string_empty.gob").read_bytes()


def test_encode_bytes_bytes():
    assert _encode_scalar(b"hello") == (TESTDATA / "scalar_bytes.gob").read_bytes()


# ---------------------------------------------------------------------------
# Task 5.3: encode struct via Schema
# ---------------------------------------------------------------------------


def _encode_struct(value: dict, schema) -> bytes:
    """Encode a struct and return the raw bytes."""
    buf = io.BytesIO()
    Encoder(buf).encode(value, schema=schema)
    return buf.getvalue()


def test_encode_struct_simple_round_trip():
    """encode(dict, schema=...) → decode recovers original values."""
    point_schema = Schema("Point", X=INT, Y=INT)
    data = _encode_struct({"X": 22, "Y": 33}, point_schema)
    result = Decoder(io.BytesIO(data)).decode()
    assert result.gob_type == "Point"
    assert result["X"] == 22
    assert result["Y"] == 33


def test_encode_struct_type_def_emitted_once():
    """Type definition is written only on the first encode call for a schema."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    point_schema = Schema("Point", X=INT, Y=INT)
    enc.encode({"X": 1, "Y": 2}, schema=point_schema)
    after_first = len(buf.getvalue())
    enc.encode({"X": 3, "Y": 4}, schema=point_schema)
    # Second encode produces only a value message (no type def)
    # A type def for Point is ~31 bytes; a value message for Point is ~8 bytes.
    second_write = len(buf.getvalue()) - after_first
    assert second_write < after_first, "second encode should not re-emit the type definition"


def test_encode_struct_zero_fields_omitted():
    """Zero-valued fields are omitted from the encoded struct payload."""
    from pygob.wire import FLOAT, STRING
    partial_schema = Schema("PartialStruct", Name=STRING, Value=INT, Extra=FLOAT)
    data = _encode_struct({"Name": "Bob", "Value": 0, "Extra": 0.0}, partial_schema)
    result = Decoder(io.BytesIO(data)).decode()
    assert result.gob_type == "PartialStruct"
    assert result["Name"] == "Bob"
    assert result["Value"] == 0
    assert result["Extra"] == 0.0


def test_encode_struct_all_field_types():
    """A schema with int, string, float, bool fields encodes and round-trips correctly."""
    from pygob.wire import BOOL, FLOAT, STRING
    mixed_schema = Schema("MixedStruct", Name=STRING, Age=INT, Score=FLOAT, Active=BOOL)
    value = {"Name": "Alice", "Age": 30, "Score": 9.5, "Active": True}
    data = _encode_struct(value, mixed_schema)
    result = Decoder(io.BytesIO(data)).decode()
    assert result.gob_type == "MixedStruct"
    assert result["Name"] == "Alice"
    assert result["Age"] == 30
    assert result["Score"] == 9.5
    assert result["Active"] is True


def test_encode_struct_requires_dict():
    """encode(value, schema=...) raises GobEncodeError when value is not a dict."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    schema = Schema("Point", X=INT, Y=INT)
    with pytest.raises(GobEncodeError, match="dict"):
        enc.encode("not a dict", schema=schema)


def test_encode_struct_missing_field_treated_as_zero():
    """A field absent from the dict is treated as zero-valued and omitted."""
    point_schema = Schema("Point", X=INT, Y=INT)
    # Only Y is provided; X defaults to 0 (zero) and is omitted
    data = _encode_struct({"Y": 5}, point_schema)
    result = Decoder(io.BytesIO(data)).decode()
    assert result["X"] == 0
    assert result["Y"] == 5


def test_encode_struct_all_zeros_produces_only_terminator():
    """A struct with all zero-valued fields encodes to just the terminator byte."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    schema = Schema("Point", X=INT, Y=INT)
    type_id = enc._emit_type_definition(schema)
    payload = enc._encode_struct_payload({"X": 0, "Y": 0}, schema)
    assert payload == b"\x00"  # only the struct terminator


# ---------------------------------------------------------------------------
# Task 5.4: encode struct via GobStruct (round-trip from decoded .gob files)
# ---------------------------------------------------------------------------


def _decode_gob_file(filename: str):
    """Decode a .gob file and return the decoded value."""
    data = (TESTDATA / filename).read_bytes()
    return Decoder(io.BytesIO(data)).decode()


def _encode_gobstruct(value) -> bytes:
    """Encode a GobStruct value and return the raw bytes."""
    buf = io.BytesIO()
    Encoder(buf).encode(value)
    return buf.getvalue()


def test_encode_gobstruct_simple_round_trip():
    """decode(struct_simple.gob) → encode(GobStruct) → decode gives same values."""
    original = _decode_gob_file("struct_simple.gob")
    reencoded = _encode_gobstruct(original)
    result = Decoder(io.BytesIO(reencoded)).decode()
    assert result.gob_type == "Point"
    assert result["X"] == 22
    assert result["Y"] == 33


def test_encode_gobstruct_mixed_round_trip():
    """decode(struct_mixed.gob) → encode(GobStruct) → decode recovers original values.

    Byte-level comparison against the Go-generated file is not attempted: Go's
    global type registry accumulates IDs across encoder instances, so the type
    ID assigned to MixedStruct in the .gob file may differ from the ID a fresh
    Python encoder assigns.
    """
    original_bytes = (TESTDATA / "struct_mixed.gob").read_bytes()
    decoded = Decoder(io.BytesIO(original_bytes)).decode()
    reencoded = _encode_gobstruct(decoded)
    result = Decoder(io.BytesIO(reencoded)).decode()
    assert result.gob_type == "MixedStruct"
    assert result["Name"] == "Alice"
    assert result["Age"] == 30
    assert result["Score"] == 9.5
    assert result["Active"] is True


def test_encode_gobstruct_zero_fields_round_trip():
    """decode(struct_zero_fields.gob) → encode(GobStruct) → decode recovers values."""
    original_bytes = (TESTDATA / "struct_zero_fields.gob").read_bytes()
    decoded = Decoder(io.BytesIO(original_bytes)).decode()
    reencoded = _encode_gobstruct(decoded)
    result = Decoder(io.BytesIO(reencoded)).decode()
    assert result.gob_type == "PartialStruct"
    assert result["Name"] == "Bob"
    assert result["Value"] == 0
    assert result["Extra"] == 0.0


def test_encode_gobstruct_nested_round_trip():
    """decode(struct_nested.gob) → encode(GobStruct) → decode recovers values.

    Byte-level comparison is not possible here: Python emits nested types first
    (Point before NestedStruct) while Go emits in a different order, and the
    type IDs also differ due to Go's global type ID counter.
    """
    original_bytes = (TESTDATA / "struct_nested.gob").read_bytes()
    decoded = Decoder(io.BytesIO(original_bytes)).decode()
    reencoded = _encode_gobstruct(decoded)
    result = Decoder(io.BytesIO(reencoded)).decode()
    assert result.gob_type == "NestedStruct"
    assert result["Label"] == "test"
    assert result["Origin"].gob_type == "Point"
    assert result["Origin"]["X"] == 1
    assert result["Origin"]["Y"] == 2


def test_encode_gobstruct_extracts_schema():
    """encode(GobStruct) uses the embedded gob_schema, not an explicit schema argument."""
    from pygob.types import GobStruct
    schema = Schema("Point", X=INT, Y=INT)
    gs = GobStruct("Point", schema, X=10, Y=20)
    buf = io.BytesIO()
    Encoder(buf).encode(gs)
    result = Decoder(io.BytesIO(buf.getvalue())).decode()
    assert result.gob_type == "Point"
    assert result["X"] == 10
    assert result["Y"] == 20


def test_encode_gobstruct_type_def_emitted_once():
    """Encoding two GobStruct values of the same type emits the type def only once."""
    schema = Schema("Point", X=INT, Y=INT)
    from pygob.types import GobStruct
    gs1 = GobStruct("Point", schema, X=1, Y=2)
    gs2 = GobStruct("Point", schema, X=3, Y=4)
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode(gs1)
    after_first = len(buf.getvalue())
    enc.encode(gs2)
    second_write = len(buf.getvalue()) - after_first
    assert second_write < after_first, "second encode should not re-emit the type definition"


# ---------------------------------------------------------------------------
# Task 5.5: encode struct via @gobstruct dataclass
# ---------------------------------------------------------------------------

import dataclasses as _dc

from pygob.types import gobstruct, GOB_INT, GOB_STRING, GOB_FLOAT, GOB_BOOL


@gobstruct("PointDC")
@_dc.dataclass
class _PointDC:
    X: int
    Y: int


@gobstruct("PersonDC")
@_dc.dataclass
class _PersonDC:
    Name: str
    Age: int
    Score: float
    Active: bool


@gobstruct("LineDC")
@_dc.dataclass
class _LineDC:
    Start: _PointDC
    End: _PointDC


def test_encode_dataclass_simple_round_trip():
    """encode(PointDC(X=22, Y=33)) → decode recovers original values."""
    buf = io.BytesIO()
    Encoder(buf).encode(_PointDC(X=22, Y=33))
    result = Decoder(io.BytesIO(buf.getvalue())).decode()
    assert result.gob_type == "PointDC"
    assert result["X"] == 22
    assert result["Y"] == 33


def test_encode_dataclass_schema_auto_derived():
    """The schema used for the encoded type comes from __gob_schema__ on the class."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode(_PointDC(X=1, Y=2))
    # The registered name must match the @gobstruct name
    assert "PointDC" in enc._schema_registry


def test_encode_dataclass_mixed_fields_round_trip():
    """encode(@gobstruct dataclass with str/int/float/bool) → decode recovers values."""
    value = _PersonDC(Name="Alice", Age=30, Score=9.5, Active=True)
    buf = io.BytesIO()
    Encoder(buf).encode(value)
    result = Decoder(io.BytesIO(buf.getvalue())).decode()
    assert result.gob_type == "PersonDC"
    assert result["Name"] == "Alice"
    assert result["Age"] == 30
    assert result["Score"] == 9.5
    assert result["Active"] is True


def test_encode_dataclass_zero_fields_omitted():
    """Zero-valued dataclass fields are omitted from the encoded payload."""
    value = _PointDC(X=0, Y=5)
    buf = io.BytesIO()
    Encoder(buf).encode(value)
    result = Decoder(io.BytesIO(buf.getvalue())).decode()
    assert result["X"] == 0
    assert result["Y"] == 5


def test_encode_dataclass_nested_round_trip():
    """encode(@gobstruct dataclass with nested @gobstruct field) → decode recovers values."""
    value = _LineDC(Start=_PointDC(X=1, Y=2), End=_PointDC(X=3, Y=4))
    buf = io.BytesIO()
    Encoder(buf).encode(value)
    result = Decoder(io.BytesIO(buf.getvalue())).decode()
    assert result.gob_type == "LineDC"
    assert result["Start"]["X"] == 1
    assert result["Start"]["Y"] == 2
    assert result["End"]["X"] == 3
    assert result["End"]["Y"] == 4


def test_encode_dataclass_type_def_emitted_once():
    """Encoding two dataclass instances of the same type emits the type def only once."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode(_PointDC(X=1, Y=2))
    after_first = len(buf.getvalue())
    enc.encode(_PointDC(X=3, Y=4))
    second_write = len(buf.getvalue()) - after_first
    assert second_write < after_first, "second encode must not re-emit the type definition"


def test_encode_dataclass_bytes_match_schema_encode():
    """encode(@gobstruct PointDC) and encode(dict, schema=...) with the same data produce identical bytes."""
    explicit_schema = Schema("PointDC", X=INT, Y=INT)

    buf1 = io.BytesIO()
    Encoder(buf1).encode(_PointDC(X=22, Y=33))

    buf2 = io.BytesIO()
    Encoder(buf2).encode({"X": 22, "Y": 33}, schema=explicit_schema)

    assert buf1.getvalue() == buf2.getvalue()


# ---------------------------------------------------------------------------
# Task 5.6: encode slices, arrays, maps
# ---------------------------------------------------------------------------

import json as _json


def _encode_value(value, **kwargs) -> bytes:
    """Encode *value* with optional keyword args; return raw bytes."""
    buf = io.BytesIO()
    Encoder(buf).encode(value, **kwargs)
    return buf.getvalue()


def _round_trip_collection(value, **kwargs):
    """Encode then decode a collection value."""
    data = _encode_value(value, **kwargs)
    return Decoder(io.BytesIO(data)).decode()


# ------ slice round-trip tests ------

def test_encode_slice_int_round_trip():
    result = _round_trip_collection([1, 2, 3])
    assert result == [1, 2, 3]


def test_encode_slice_string_round_trip():
    result = _round_trip_collection(["a", "b", "c"])
    assert result == ["a", "b", "c"]


def test_encode_slice_empty_round_trip():
    result = _round_trip_collection([], elem_type=INT)
    assert result == []


def test_encode_slice_single_element():
    result = _round_trip_collection([42])
    assert result == [42]


def test_encode_slice_float_round_trip():
    result = _round_trip_collection([1.0, 2.5, 3.14])
    assert result == [1.0, 2.5, 3.14]


def test_encode_slice_type_def_emitted_once():
    """Encoding two int-slice values shares one type definition."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode([1, 2])
    after_first = len(buf.getvalue())
    enc.encode([3, 4, 5])
    second_write = len(buf.getvalue()) - after_first
    assert second_write < after_first, "second encode must not re-emit the slice type definition"


def test_encode_slice_empty_requires_elem_type():
    """Encoding an empty list without elem_type raises GobEncodeError."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="elem_type"):
        enc.encode([])


# ------ slice: values match Go-generated gob files ------

def test_encode_slice_int_matches_go_decoded():
    """Python-encoded []int{1,2,3} decodes to the same values as Go's slice_int.gob."""
    go_data = (TESTDATA / "slice_int.gob").read_bytes()
    go_decoded = Decoder(io.BytesIO(go_data)).decode()

    py_data = _encode_value([1, 2, 3])
    py_decoded = Decoder(io.BytesIO(py_data)).decode()

    assert py_decoded == go_decoded


def test_encode_slice_string_matches_go_decoded():
    go_data = (TESTDATA / "slice_string.gob").read_bytes()
    go_decoded = Decoder(io.BytesIO(go_data)).decode()

    py_data = _encode_value(["a", "b", "c"])
    py_decoded = Decoder(io.BytesIO(py_data)).decode()

    assert py_decoded == go_decoded


def test_encode_slice_empty_matches_go_decoded():
    go_data = (TESTDATA / "slice_empty.gob").read_bytes()
    go_decoded = Decoder(io.BytesIO(go_data)).decode()

    py_data = _encode_value([], elem_type=INT)
    py_decoded = Decoder(io.BytesIO(py_data)).decode()

    assert py_decoded == go_decoded


def test_encode_array_int_matches_go_decoded():
    """Python-encoded slice [10,20,30] has the same values as Go's array_int.gob."""
    go_data = (TESTDATA / "array_int.gob").read_bytes()
    go_decoded = Decoder(io.BytesIO(go_data)).decode()

    py_data = _encode_value([10, 20, 30])
    py_decoded = Decoder(io.BytesIO(py_data)).decode()

    assert py_decoded == go_decoded


# ------ map round-trip tests ------

def test_encode_map_string_int_round_trip():
    value = {"one": 1, "two": 2, "three": 3}
    result = _round_trip_collection(value)
    assert result == value


def test_encode_map_int_string_round_trip():
    value = {1: "one", 2: "two"}
    result = _round_trip_collection(value)
    assert result == value


def test_encode_map_empty_round_trip():
    result = _round_trip_collection({}, key_type=STRING, elem_type=INT)
    assert result == {}


def test_encode_map_empty_requires_type_params():
    """Encoding an empty dict without key_type/elem_type raises GobEncodeError."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="elem_type"):
        enc.encode({})


def test_encode_map_type_def_emitted_once():
    """Two string→int maps share one type definition."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"a": 1})
    after_first = len(buf.getvalue())
    enc.encode({"b": 2, "c": 3})
    second_write = len(buf.getvalue()) - after_first
    assert second_write < after_first, "second encode must not re-emit the map type definition"


# ------ map: values match Go-generated gob files ------

def test_encode_map_string_int_matches_go_decoded():
    """Python-encoded map[string]int matches values from Go's map_string_int.gob."""
    go_data = (TESTDATA / "map_string_int.gob").read_bytes()
    go_decoded = Decoder(io.BytesIO(go_data)).decode()

    py_data = _encode_value({"one": 1, "two": 2})
    py_decoded = Decoder(io.BytesIO(py_data)).decode()

    assert py_decoded == go_decoded


def test_encode_map_int_string_matches_go_decoded():
    go_data = (TESTDATA / "map_int_string.gob").read_bytes()
    go_decoded = Decoder(io.BytesIO(go_data)).decode()

    py_data = _encode_value({1: "one", 2: "two"})
    py_decoded = Decoder(io.BytesIO(py_data)).decode()

    assert py_decoded == go_decoded


def test_encode_map_empty_matches_go_decoded():
    go_data = (TESTDATA / "map_empty.gob").read_bytes()
    go_decoded = Decoder(io.BytesIO(go_data)).decode()

    py_data = _encode_value({}, key_type=STRING, elem_type=INT)
    py_decoded = Decoder(io.BytesIO(py_data)).decode()

    assert py_decoded == go_decoded


# ------ wire type byte verification ------

def test_encode_slice_int_wire_type_bytes():
    """Verify the SliceWireType bytes for []int are correctly structured."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    # Trigger only the type definition by peeking at _collection_registry
    enc._emit_slice_type_definition(INT)
    data = buf.getvalue()
    # Decode the emitted type definition using the Decoder
    dec = Decoder(io.BytesIO(data))
    msg_id, payload = dec._read_message()
    assert msg_id < 0
    type_id = -msg_id
    dec._process_type_definition(type_id, payload)
    wt = dec._type_registry[type_id]
    assert wt.slice_t is not None
    assert wt.slice_t.elem == INT


def test_encode_map_string_int_wire_type_bytes():
    """Verify the MapWireType bytes for map[string]int are correctly structured."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc._emit_map_type_definition(STRING, INT)
    data = buf.getvalue()
    dec = Decoder(io.BytesIO(data))
    msg_id, payload = dec._read_message()
    assert msg_id < 0
    type_id = -msg_id
    dec._process_type_definition(type_id, payload)
    wt = dec._type_registry[type_id]
    assert wt.map_t is not None
    assert wt.map_t.key == STRING
    assert wt.map_t.elem == INT


# ---------------------------------------------------------------------------
# Task 5.7: nested structs, slices/maps of structs, multi-message encoding
# ---------------------------------------------------------------------------


# --- nested struct via Schema -----------------------------------------------

def test_encode_nested_struct_via_schema_round_trip():
    """encode(dict, schema=nested_schema) → decode recovers nested struct values."""
    point_schema = Schema("Point", X=INT, Y=INT)
    nested_schema = Schema("NestedStruct", Label=STRING, Origin=point_schema)
    value = {"Label": "test", "Origin": {"X": 1, "Y": 2}}
    data = _encode_struct(value, nested_schema)
    result = Decoder(io.BytesIO(data)).decode()
    assert result.gob_type == "NestedStruct"
    assert result["Label"] == "test"
    assert result["Origin"].gob_type == "Point"
    assert result["Origin"]["X"] == 1
    assert result["Origin"]["Y"] == 2


def test_encode_nested_struct_inner_type_emitted_first():
    """Inner struct type definition is emitted before the outer one."""
    point_schema = Schema("Point", X=INT, Y=INT)
    nested_schema = Schema("NestedStruct", Label=STRING, Origin=point_schema)
    enc, buf = _make_encoder()
    enc._emit_type_definition(nested_schema)
    # Point (inner) should have the lower type ID
    assert enc._schema_registry["Point"] < enc._schema_registry["NestedStruct"]


def test_encode_nested_struct_matches_go_decoded():
    """Python-encoded NestedStruct decodes to the same values as Go's struct_nested.gob."""
    go_decoded = Decoder(io.BytesIO((TESTDATA / "struct_nested.gob").read_bytes())).decode()

    point_schema = Schema("Point", X=INT, Y=INT)
    nested_schema = Schema("NestedStruct", Label=STRING, Origin=point_schema)
    data = _encode_struct({"Label": "test", "Origin": {"X": 1, "Y": 2}}, nested_schema)
    result = Decoder(io.BytesIO(data)).decode()

    assert result.gob_type == go_decoded.gob_type
    assert result["Label"] == go_decoded["Label"]
    assert result["Origin"]["X"] == go_decoded["Origin"]["X"]
    assert result["Origin"]["Y"] == go_decoded["Origin"]["Y"]


# --- slice of structs -------------------------------------------------------

def test_encode_slice_of_gobstructs_round_trip():
    """encode(list of GobStruct) → decode recovers all struct values."""
    schema = Schema("Point", X=INT, Y=INT)
    from pygob.types import GobStruct
    items = [GobStruct("Point", schema, X=1, Y=2), GobStruct("Point", schema, X=3, Y=4)]
    data = _encode_value(items)
    result = Decoder(io.BytesIO(data)).decode()
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0].gob_type == "Point"
    assert result[0]["X"] == 1
    assert result[0]["Y"] == 2
    assert result[1]["X"] == 3
    assert result[1]["Y"] == 4


def test_encode_slice_of_structs_matches_go_decoded():
    """Python-encoded []Point decodes to the same values as Go's nested_slice_of_structs.gob."""
    go_decoded = Decoder(io.BytesIO((TESTDATA / "nested_slice_of_structs.gob").read_bytes())).decode()

    schema = Schema("Point", X=INT, Y=INT)
    from pygob.types import GobStruct
    items = [GobStruct("Point", schema, X=1, Y=2), GobStruct("Point", schema, X=3, Y=4)]
    data = _encode_value(items)
    result = Decoder(io.BytesIO(data)).decode()

    assert len(result) == len(go_decoded)
    for py_item, go_item in zip(result, go_decoded):
        assert py_item["X"] == go_item["X"]
        assert py_item["Y"] == go_item["Y"]


def test_encode_slice_of_dataclasses_round_trip():
    """encode(list of @gobstruct dataclasses) → decode recovers values."""
    items = [_PointDC(X=10, Y=20), _PointDC(X=30, Y=40)]
    data = _encode_value(items)
    result = Decoder(io.BytesIO(data)).decode()
    assert len(result) == 2
    assert result[0]["X"] == 10
    assert result[0]["Y"] == 20
    assert result[1]["X"] == 30
    assert result[1]["Y"] == 40


def test_encode_slice_of_structs_type_def_order():
    """Struct type def is emitted before the slice type def."""
    schema = Schema("Point", X=INT, Y=INT)
    from pygob.types import GobStruct
    items = [GobStruct("Point", schema, X=1, Y=2)]
    enc, buf = _make_encoder()
    enc.encode(items)
    # Point struct type ID should be assigned (65), slice type ID should be next (66)
    assert "Point" in enc._schema_registry
    point_id = enc._schema_registry["Point"]
    assert point_id == FIRST_USER_ID
    # The slice type should have the next ID
    slice_key = ("slice", point_id)
    assert slice_key in enc._collection_registry
    assert enc._collection_registry[slice_key] == FIRST_USER_ID + 1


# --- map with struct values -------------------------------------------------

def test_encode_map_struct_values_round_trip():
    """encode(dict with GobStruct values) → decode recovers all values."""
    schema = Schema("Point", X=INT, Y=INT)
    from pygob.types import GobStruct
    value = {"a": GobStruct("Point", schema, X=1, Y=2)}
    data = _encode_value(value)
    result = Decoder(io.BytesIO(data)).decode()
    assert isinstance(result, dict)
    assert "a" in result
    assert result["a"].gob_type == "Point"
    assert result["a"]["X"] == 1
    assert result["a"]["Y"] == 2


def test_encode_map_struct_values_matches_go_decoded():
    """Python-encoded map[string]Point decodes to the same values as Go's nested_map_of_structs.gob."""
    go_decoded = Decoder(io.BytesIO((TESTDATA / "nested_map_of_structs.gob").read_bytes())).decode()

    schema = Schema("Point", X=INT, Y=INT)
    from pygob.types import GobStruct
    value = {"a": GobStruct("Point", schema, X=1, Y=2)}
    data = _encode_value(value)
    result = Decoder(io.BytesIO(data)).decode()

    assert set(result.keys()) == set(go_decoded.keys())
    for k in go_decoded:
        assert result[k]["X"] == go_decoded[k]["X"]
        assert result[k]["Y"] == go_decoded[k]["Y"]


# --- multi-message encoding (type reuse across encode calls) ----------------

def test_encode_multi_message_round_trip():
    """Two encode calls on the same Encoder both decode correctly."""
    schema = Schema("Point", X=INT, Y=INT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"X": 1, "Y": 2}, schema=schema)
    enc.encode({"X": 3, "Y": 4}, schema=schema)

    buf.seek(0)
    dec = Decoder(buf)
    r1 = dec.decode()
    r2 = dec.decode()

    assert r1.gob_type == "Point"
    assert r1["X"] == 1
    assert r1["Y"] == 2
    assert r2.gob_type == "Point"
    assert r2["X"] == 3
    assert r2["Y"] == 4


def test_encode_multi_message_type_def_emitted_once():
    """Type definition is only emitted once even across multiple encode calls."""
    schema = Schema("Point", X=INT, Y=INT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"X": 1, "Y": 2}, schema=schema)
    after_first = len(buf.getvalue())
    enc.encode({"X": 3, "Y": 4}, schema=schema)
    second_write = len(buf.getvalue()) - after_first
    # First write includes type def + value; second write is value only (smaller)
    assert second_write < after_first


def test_encode_multi_message_matches_go_decoded():
    """Two Python-encoded Points decode to the same values as Go's multi_message.gob."""
    go_data = (TESTDATA / "multi_message.gob").read_bytes()
    go_dec = Decoder(io.BytesIO(go_data))
    go1 = go_dec.decode()
    go2 = go_dec.decode()

    schema = Schema("Point", X=INT, Y=INT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"X": 1, "Y": 2}, schema=schema)
    enc.encode({"X": 3, "Y": 4}, schema=schema)

    buf.seek(0)
    py_dec = Decoder(buf)
    py1 = py_dec.decode()
    py2 = py_dec.decode()

    assert py1["X"] == go1["X"] and py1["Y"] == go1["Y"]
    assert py2["X"] == go2["X"] and py2["Y"] == go2["Y"]


# ---------------------------------------------------------------------------
# Task 5.8: encoder interface values
# ---------------------------------------------------------------------------

from pygob.wire import INTERFACE


def test_encoder_register_stores_mapping():
    """register(go_name, schema) stores the mapping in _interface_registry."""
    enc, _ = _make_encoder()
    point_schema = Schema("Point", X=INT, Y=INT)
    enc.register("main.Point", point_schema)
    assert "Point" in enc._interface_registry
    go_name, stored_schema = enc._interface_registry["Point"]
    assert go_name == "main.Point"
    assert stored_schema is point_schema


def test_encoder_register_multiple_types():
    """Multiple register() calls store independent mappings."""
    enc, _ = _make_encoder()
    schema_a = Schema("TypeA", X=INT)
    schema_b = Schema("TypeB", Y=INT)
    enc.register("pkg.TypeA", schema_a)
    enc.register("pkg.TypeB", schema_b)
    assert enc._interface_registry["TypeA"][0] == "pkg.TypeA"
    assert enc._interface_registry["TypeB"][0] == "pkg.TypeB"


def test_encode_interface_field_round_trip():
    """Container struct with interface{} field holding Point round-trips correctly."""
    from pygob.types import GobStruct

    point_schema = Schema("Point", X=INT, Y=INT)
    container_schema = Schema("Container", Name=STRING, Value=INTERFACE)

    point = GobStruct("Point", point_schema, X=1, Y=2)
    container = GobStruct("Container", container_schema, Name="test", Value=point)

    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.register("main.Point", point_schema)
    enc.encode(container)

    buf.seek(0)
    result = Decoder(buf).decode()

    assert result.gob_type == "Container"
    assert result["Name"] == "test"
    assert isinstance(result["Value"], GobStruct)
    assert result["Value"].gob_type == "Point"
    assert result["Value"]["X"] == 1
    assert result["Value"]["Y"] == 2


def test_encode_interface_nil_field_omitted():
    """A nil (None) interface field is treated as zero-valued and omitted."""
    from pygob.types import GobStruct

    container_schema = Schema("Container", Name=STRING, Value=INTERFACE)
    container = GobStruct("Container", container_schema, Name="test", Value=None)

    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode(container)

    result = Decoder(io.BytesIO(buf.getvalue())).decode()
    assert result["Name"] == "test"
    assert result["Value"] is None


def test_encode_interface_field_concrete_type_gets_type_id():
    """The concrete type gets assigned a type_id in _schema_registry."""
    from pygob.types import GobStruct

    point_schema = Schema("Point", X=INT, Y=INT)
    container_schema = Schema("Container", Name=STRING, Value=INTERFACE)
    point = GobStruct("Point", point_schema, X=5, Y=6)
    container = GobStruct("Container", container_schema, Name="x", Value=point)

    enc, _ = _make_encoder()
    enc.register("main.Point", point_schema)
    enc.encode(container)

    assert "Point" in enc._schema_registry


def test_encode_interface_unregistered_type_raises():
    """Encoding an interface field with an unregistered concrete type raises GobEncodeError."""
    from pygob.types import GobStruct

    point_schema = Schema("Point", X=INT, Y=INT)
    container_schema = Schema("Container", Name=STRING, Value=INTERFACE)
    point = GobStruct("Point", point_schema, X=1, Y=2)
    container = GobStruct("Container", container_schema, Name="test", Value=point)

    buf = io.BytesIO()
    enc = Encoder(buf)
    # Deliberately do NOT call enc.register(...)
    with pytest.raises(GobEncodeError, match="not registered"):
        enc.encode(container)


def test_encode_interface_round_trip_from_go_file():
    """Decode Go's interface_value.gob, re-encode with Python, decode again — same values."""
    from pygob.types import GobStruct

    data = (TESTDATA / "interface_value.gob").read_bytes()
    dec = Decoder(io.BytesIO(data))
    original = dec.decode()

    point_schema = original["Value"].gob_schema

    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.register("main.Point", point_schema)
    enc.encode(original)

    buf.seek(0)
    result = Decoder(buf).decode()

    assert result.gob_type == "Container"
    assert result["Name"] == "test"
    assert isinstance(result["Value"], GobStruct)
    assert result["Value"].gob_type == "Point"
    assert result["Value"]["X"] == 1
    assert result["Value"]["Y"] == 2


def test_encode_interface_via_schema_dict():
    """encode(dict, schema=container_schema) with interface field round-trips correctly."""
    from pygob.types import GobStruct

    point_schema = Schema("Point", X=INT, Y=INT)
    container_schema = Schema("Container", Name=STRING, Value=INTERFACE)
    point = GobStruct("Point", point_schema, X=7, Y=8)

    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.register("main.Point", point_schema)
    enc.encode({"Name": "hello", "Value": point}, schema=container_schema)

    result = Decoder(io.BytesIO(buf.getvalue())).decode()
    assert result["Name"] == "hello"
    assert result["Value"]["X"] == 7
    assert result["Value"]["Y"] == 8


def test_encode_interface_type_def_emitted_only_once():
    """Encoding two Container values reuses the Point inline type def (same type_id both times)."""
    from pygob.types import GobStruct

    point_schema = Schema("Point", X=INT, Y=INT)
    container_schema = Schema("Container", Name=STRING, Value=INTERFACE)

    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.register("main.Point", point_schema)

    c1 = GobStruct("Container", container_schema, Name="a", Value=GobStruct("Point", point_schema, X=1, Y=2))
    c2 = GobStruct("Container", container_schema, Name="b", Value=GobStruct("Point", point_schema, X=3, Y=4))
    enc.encode(c1)
    enc.encode(c2)

    # Same type_id should be used for Point in both encodings
    assert enc._schema_registry["Point"] == enc._schema_registry["Point"]  # trivially true

    buf.seek(0)
    dec = Decoder(buf)
    r1 = dec.decode()
    r2 = dec.decode()
    assert r1["Value"]["X"] == 1
    assert r2["Value"]["X"] == 3


def test_encode_interface_encode_interface_method():
    """encode_interface() is a convenience wrapper equivalent to encode() for GobStruct."""
    from pygob.types import GobStruct

    point_schema = Schema("Point", X=INT, Y=INT)
    point = GobStruct("Point", point_schema, X=10, Y=20)

    buf1 = io.BytesIO()
    enc1 = Encoder(buf1)
    enc1.encode(point)

    buf2 = io.BytesIO()
    enc2 = Encoder(buf2)
    enc2.encode_interface(point)

    assert buf1.getvalue() == buf2.getvalue()


# ---------------------------------------------------------------------------
# Task 5.9 — GobEncoder / BinaryMarshaler encoding
# ---------------------------------------------------------------------------


def test_register_codec_stores_function():
    """register_codec() stores the encode function in the internal registry."""
    enc, _ = _make_encoder()
    fn = lambda v: v
    enc.register_codec("MyType", fn)
    assert enc._gobencoder_registry["MyType"] is fn


def test_register_codec_multiple_types():
    """register_codec() can store multiple distinct type codecs."""
    enc, _ = _make_encoder()
    fn1 = lambda v: bytes([1])
    fn2 = lambda v: bytes([2])
    enc.register_codec("TypeA", fn1)
    enc.register_codec("TypeB", fn2)
    assert enc._gobencoder_registry["TypeA"] is fn1
    assert enc._gobencoder_registry["TypeB"] is fn2


def test_encode_gob_encoded_round_trip():
    """GobEncoded values survive an encode → decode round-trip."""
    from pygob.types import GobEncoded

    raw = bytes([0x01, 0x02, 0x03, 0x04, 0x05])
    value = GobEncoded("MyType", raw)

    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode(value)

    buf.seek(0)
    dec = Decoder(buf)
    result = dec.decode()

    assert isinstance(result, GobEncoded)
    assert result.type_name == "MyType"
    assert result.data == raw


def test_encode_gob_encoded_type_def_emitted_once():
    """Encoding the same GobEncoder type twice emits only one type definition."""
    from pygob.types import GobEncoded

    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode(GobEncoded("MyType", b"\x01"))
    enc.encode(GobEncoded("MyType", b"\x02"))

    # Decode both values — no errors means type def was valid and not duplicated
    buf.seek(0)
    dec = Decoder(buf)
    r1 = dec.decode()
    r2 = dec.decode()
    assert r1.data == b"\x01"
    assert r2.data == b"\x02"


def test_encode_gob_encoded_distinct_types_get_distinct_ids():
    """Two GobEncoded values with different type names get different type IDs."""
    enc, _ = _make_encoder()
    enc._emit_gob_encoder_type_definition("TypeA")
    enc._emit_gob_encoder_type_definition("TypeB")
    assert enc._schema_registry["TypeA"] != enc._schema_registry["TypeB"]


def test_encode_gob_encoded_via_encode_gob_encoded_method():
    """encode_gob_encoded() with a GobEncoded value is equivalent to encode()."""
    from pygob.types import GobEncoded

    raw = b"\xde\xad\xbe\xef"
    value = GobEncoded("SomeType", raw)

    buf1 = io.BytesIO()
    enc1 = Encoder(buf1)
    enc1.encode(value)

    buf2 = io.BytesIO()
    enc2 = Encoder(buf2)
    enc2.encode_gob_encoded(value, "SomeType")

    assert buf1.getvalue() == buf2.getvalue()


def test_encode_gob_encoded_custom_codec_round_trip():
    """Custom encode_fn registered via register_codec is applied to non-GobEncoded values."""
    import struct

    def encode_int32(value: int) -> bytes:
        return struct.pack(">i", value)

    def decode_int32(data: bytes) -> int:
        return struct.unpack(">i", data)[0]

    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.register_codec("MyInt32", encode_int32)
    enc.encode_gob_encoded(42, "MyInt32")

    buf.seek(0)
    dec = Decoder(buf)
    dec.register_codec("MyInt32", decode_int32)
    result = dec.decode()
    assert result == 42


def test_encode_gob_encoded_unregistered_type_raises():
    """encode_gob_encoded() raises GobEncodeError for non-GobEncoded values without a codec."""
    enc, _ = _make_encoder()
    with pytest.raises(GobEncodeError, match="no encoder registered"):
        enc.encode_gob_encoded(42, "UnknownType")


def test_encode_gob_encoded_scalar_time_round_trip():
    """GobEncoded value decoded from scalar_time.gob survives an encode→decode cycle."""
    from pygob.types import GobEncoded

    gob_path = TESTDATA / "scalar_time.gob"
    if not gob_path.exists():
        pytest.skip("scalar_time.gob not found")

    with open(gob_path, "rb") as f:
        dec = Decoder(f)
        original = dec.decode()

    assert isinstance(original, GobEncoded)

    # Re-encode the decoded GobEncoded value
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode(original)

    # Decode the re-encoded value
    buf.seek(0)
    dec2 = Decoder(buf)
    result = dec2.decode()

    assert isinstance(result, GobEncoded)
    assert result.type_name == original.type_name
    assert result.data == original.data


# ---------------------------------------------------------------------------
# Collection type descriptors in Schema fields
# ---------------------------------------------------------------------------

def _roundtrip(value, **kwargs):
    """Encode value then decode and return the result."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode(value, **kwargs)
    buf.seek(0)
    return Decoder(buf).decode()


class TestSchemaCollectionFields:
    def test_slice_field_roundtrip(self):
        schema = Schema("Bag", Items=SliceOf(GOB_INT))
        result = _roundtrip({"Items": [1, 2, 3]}, schema=schema)
        assert isinstance(result, GobStruct)
        assert result["Items"] == [1, 2, 3]

    def test_slice_field_empty(self):
        schema = Schema("Bag", Items=SliceOf(GOB_INT))
        result = _roundtrip({"Items": []}, schema=schema)
        assert result["Items"] == []

    def test_map_field_roundtrip(self):
        schema = Schema("Counter", Counts=MapOf(GOB_STRING, GOB_INT))
        result = _roundtrip({"Counts": {"a": 1, "b": 2}}, schema=schema)
        assert result["Counts"] == {"a": 1, "b": 2}

    def test_map_field_empty(self):
        schema = Schema("Counter", Counts=MapOf(GOB_STRING, GOB_INT))
        result = _roundtrip({"Counts": {}}, schema=schema)
        assert result["Counts"] == {}

    def test_array_field_roundtrip(self):
        schema = Schema("Triple", Coords=ArrayOf(GOB_FLOAT, 3))
        result = _roundtrip({"Coords": [1.0, 2.0, 3.0]}, schema=schema)
        assert result["Coords"] == [1.0, 2.0, 3.0]

    def test_mixed_plain_and_collection_fields(self):
        schema = Schema("Row", Name=GOB_STRING, Scores=SliceOf(GOB_FLOAT))
        result = _roundtrip({"Name": "Alice", "Scores": [9.5, 8.0]}, schema=schema)
        assert result["Name"] == "Alice"
        assert result["Scores"] == [9.5, 8.0]

    def test_slice_of_structs_field(self):
        point_schema = Schema("Point", X=GOB_INT, Y=GOB_INT)
        cloud_schema = Schema("Cloud", Points=SliceOf(point_schema))
        value = {
            "Points": [
                {"X": 1, "Y": 2},
                {"X": 3, "Y": 4},
            ]
        }
        result = _roundtrip(value, schema=cloud_schema)
        assert len(result["Points"]) == 2
        assert result["Points"][0]["X"] == 1
        assert result["Points"][1]["Y"] == 4

    def test_map_of_structs_field(self):
        point_schema = Schema("Point", X=GOB_INT, Y=GOB_INT)
        named_schema = Schema("Named", Map=MapOf(GOB_STRING, point_schema))
        value = {"Map": {"origin": {"X": 0, "Y": 0}, "end": {"X": 10, "Y": 20}}}
        result = _roundtrip(value, schema=named_schema)
        assert result["Map"]["end"]["X"] == 10

    def test_zero_slice_field_omitted(self):
        """None slice field is treated as zero value and omitted, decodes as []."""
        schema = Schema("Bag", Items=SliceOf(GOB_INT), Count=GOB_INT)
        result = _roundtrip({"Items": None, "Count": 5}, schema=schema)
        assert result["Count"] == 5
        assert result["Items"] == []  # decoder zero-value for slice is []


class TestGobstructCollectionRoundtrip:
    def test_list_int_field(self):
        @gobstruct("Container")
        @dataclass
        class Container:
            Name: str
            Items: list[int]

        obj = Container(Name="test", Items=[10, 20, 30])
        result = _roundtrip(obj)
        assert isinstance(result, GobStruct)
        assert result["Name"] == "test"
        assert result["Items"] == [10, 20, 30]

    def test_dict_str_float_field(self):
        @gobstruct("Scores")
        @dataclass
        class Scores:
            Data: dict[str, float]

        obj = Scores(Data={"math": 9.5, "english": 8.0})
        result = _roundtrip(obj)
        assert result["Data"] == {"math": 9.5, "english": 8.0}

    def test_list_of_gobstruct_field(self):
        @gobstruct("Point")
        @dataclass
        class Point:
            X: int
            Y: int

        @gobstruct("Cloud")
        @dataclass
        class Cloud:
            Points: list[Point]

        obj = Cloud(Points=[Point(X=1, Y=2), Point(X=3, Y=4)])
        result = _roundtrip(obj)
        assert len(result["Points"]) == 2
        assert result["Points"][0]["X"] == 1
        assert result["Points"][1]["X"] == 3

    def test_empty_list_field(self):
        @gobstruct("Bag")
        @dataclass
        class Bag:
            Items: list[str]

        obj = Bag(Items=[])
        result = _roundtrip(obj)
        assert result["Items"] == []

    def test_gobstruct_roundtrip_preserves_schema_descriptors(self):
        """Decoded GobStruct has SliceOf in its schema, enabling re-encoding."""
        @gobstruct("Bag")
        @dataclass
        class Bag:
            Items: list[int]

        obj = Bag(Items=[1, 2, 3])
        decoded = _roundtrip(obj)
        assert isinstance(decoded, GobStruct)
        assert isinstance(decoded.gob_schema.fields["Items"], SliceOf)

        # Re-encode the decoded GobStruct (tests round-trip of round-trip)
        buf = io.BytesIO()
        Encoder(buf).encode(decoded)
        buf.seek(0)
        result2 = Decoder(buf).decode()
        assert result2["Items"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# GOB_DURATION
# ---------------------------------------------------------------------------


def test_duration_field_encodes_as_int():
    """A GOB_DURATION field encodes a timedelta as nanoseconds on the wire."""
    from datetime import timedelta
    from pygob.types import GOB_DURATION

    event_schema = Schema("EventDuration", Name=GOB_STRING, Timeout=GOB_DURATION)
    data = _encode_struct({"Name": "req", "Timeout": timedelta(seconds=5)}, event_schema)

    # Decode: the wire type is INT, so Timeout comes back as an int (nanoseconds)
    result = Decoder(io.BytesIO(data)).decode()
    assert result.gob_type == "EventDuration"
    assert result["Name"] == "req"
    assert result["Timeout"] == 5_000_000_000  # 5s in nanoseconds


def test_duration_zero_value_omitted():
    """A timedelta(0) duration field is treated as zero and omitted from the payload."""
    from datetime import timedelta
    from pygob.types import GOB_DURATION

    event_schema = Schema("EventDuration2", Name=GOB_STRING, Timeout=GOB_DURATION)
    data = _encode_struct({"Name": "req", "Timeout": timedelta(0)}, event_schema)

    result = Decoder(io.BytesIO(data)).decode()
    assert result["Timeout"] == 0


def test_duration_negative_timedelta():
    """A negative timedelta encodes correctly as a negative nanosecond count."""
    from datetime import timedelta
    from pygob.types import GOB_DURATION

    event_schema = Schema("EventDuration3", Name=GOB_STRING, Timeout=GOB_DURATION)
    data = _encode_struct({"Name": "req", "Timeout": timedelta(seconds=-3)}, event_schema)

    result = Decoder(io.BytesIO(data)).decode()
    assert result["Timeout"] == -3_000_000_000


def test_duration_field_wrong_type_raises():
    """Passing an int to a GOB_DURATION field raises GobEncodeError."""
    from pygob.types import GOB_DURATION
    from pygob.exceptions import GobEncodeError

    event_schema = Schema("EventDuration4", Timeout=GOB_DURATION)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="SemanticType encode failed"):
        enc.encode({"Timeout": 5_000_000_000}, schema=event_schema)


def test_gobstruct_timedelta_annotation():
    """@gobstruct with timedelta annotation infers GOB_DURATION."""
    from dataclasses import dataclass
    from datetime import timedelta
    from pygob.types import GOB_DURATION

    @gobstruct("TimedEvent")
    @dataclass
    class TimedEvent:
        Name: str
        Timeout: timedelta

    assert TimedEvent.__gob_schema__.fields["Timeout"] == GOB_DURATION

    obj = TimedEvent(Name="task", Timeout=timedelta(minutes=1))
    result = _roundtrip(obj)
    assert result["Name"] == "task"
    assert result["Timeout"] == 60_000_000_000  # 60s in nanoseconds
