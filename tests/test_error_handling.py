"""Tests for error handling and edge cases (Task 6.3).

Covers:
  - Truncated streams → GobDecodeError
  - Unknown type IDs → GobDecodeError
  - Type mismatch on encode → GobEncodeError
  - Missing required registrations → GobEncodeError
"""

from __future__ import annotations

import io

import pytest

from pygob.codec import decode_uint, encode_int, encode_uint
from pygob.decoder import Decoder
from pygob.encoder import Encoder
from pygob.exceptions import GobDecodeError, GobEncodeError
from pygob.types import GobEncoded, GobStruct, Schema
from pygob.wire import BOOL, BYTES, COMPLEX, FLOAT, INT, STRING, UINT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_value_message(type_id: int, payload: bytes) -> bytes:
    """Craft a minimal framed value message with the given type_id and payload."""
    msg = encode_int(type_id) + payload
    return encode_uint(len(msg)) + msg


def _make_type_def_message(type_id: int, wire_bytes: bytes) -> bytes:
    """Craft a minimal framed type-definition message."""
    msg = encode_int(-type_id) + wire_bytes
    return encode_uint(len(msg)) + msg


# ---------------------------------------------------------------------------
# Truncated streams → GobDecodeError
# ---------------------------------------------------------------------------


def test_truncated_empty_stream_raises():
    """Decoding an empty stream raises GobDecodeError on byte-count read."""
    dec = Decoder(io.BytesIO(b""))
    with pytest.raises(GobDecodeError):
        dec.decode()


def test_truncated_byte_count_partial():
    """A stream truncated in the middle of the byte-count field raises GobDecodeError."""
    # Header byte 0xfe means "read 2 more bytes for the length", but we only give 1.
    data = b"\xfe\x0a"  # claims 2-byte count but only 1 byte follows
    dec = Decoder(io.BytesIO(data))
    with pytest.raises(GobDecodeError):
        dec.decode()


def test_truncated_message_body_raises():
    """A stream whose byte-count exceeds available bytes raises GobDecodeError."""
    # Byte count = 10, but only 4 bytes of body follow
    data = encode_uint(10) + b"\x01\x02\x03\x04"
    dec = Decoder(io.BytesIO(data))
    with pytest.raises(GobDecodeError):
        dec.decode()


def test_truncated_uint_multi_byte_raises():
    """decode_uint on a truncated multi-byte integer raises GobDecodeError."""
    # 0xfe = need 2 bytes, but only 1 follows
    with pytest.raises(GobDecodeError, match="truncated|too short"):
        decode_uint(b"\xfe\x00")  # need 2 bytes after header, only 1


def test_truncated_uint_empty_raises():
    """decode_uint on an empty buffer raises GobDecodeError."""
    with pytest.raises(GobDecodeError, match="empty|end of stream"):
        decode_uint(b"")


def test_truncated_string_in_message():
    """A string field whose length exceeds available data raises GobDecodeError."""
    # Build a scalar string message that claims 100 bytes but provides fewer.
    # Singleton wrapper: 0x00 + uint(100) + <only 5 bytes>
    payload = b"\x00" + encode_uint(100) + b"hello"
    data = _make_value_message(STRING, payload)
    dec = Decoder(io.BytesIO(data))
    with pytest.raises(GobDecodeError):
        dec.decode()


def test_truncated_bytes_in_message():
    """A bytes field whose length exceeds available data raises GobDecodeError."""
    payload = b"\x00" + encode_uint(50) + b"hi"
    data = _make_value_message(BYTES, payload)
    dec = Decoder(io.BytesIO(data))
    with pytest.raises(GobDecodeError):
        dec.decode()


def test_truncated_scalar_missing_singleton_marker():
    """A scalar payload missing the 0x00 marker raises GobDecodeError."""
    # An int payload that skips the singleton 0x00 wrapper
    payload = encode_int(42)  # no 0x00 prefix
    data = _make_value_message(INT, payload)
    dec = Decoder(io.BytesIO(data))
    with pytest.raises(GobDecodeError, match="singleton marker"):
        dec.decode()


def test_truncated_collection_missing_singleton_marker():
    """A collection payload missing the 0x00 marker raises GobDecodeError."""
    # We need a registered slice type. We can't easily craft one without
    # registering the type. Instead, verify the error path via a known
    # encoder output with the marker byte stripped.
    from pygob.wire import FIRST_USER_ID

    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode([1, 2, 3], elem_type=INT)
    encoded = buf.getvalue()

    # The last framed message is the value message. Identify it and corrupt
    # the singleton 0x00 byte (first byte of the value payload after type_id).
    # We do this by finding the last message and flipping its marker.
    # Simpler: build the stream up to the value message, then corrupt it.

    # Re-encode to find offsets: type-def message + value message.
    buf2 = io.BytesIO()
    enc2 = Encoder(buf2)
    enc2.encode([1, 2, 3], elem_type=INT)
    all_bytes = bytearray(buf2.getvalue())

    # The value message is the last framed chunk. Find the start of the last
    # message by decoding byte counts from the beginning.
    pos = 0
    message_starts = []
    view = bytes(all_bytes)
    while pos < len(view):
        count, n = decode_uint(view[pos:])
        message_starts.append(pos)
        pos += n + count

    # Corrupt the singleton marker in the last message payload.
    last_msg_start = message_starts[-1]
    count, n = decode_uint(view[last_msg_start:])
    # Last message layout: uint(count) | int(type_id) ... | 0x00 | payload
    # The 0x00 is after the type_id int. Flip it to 0x01.
    msg_body_start = last_msg_start + n
    msg_body = bytearray(view[msg_body_start: msg_body_start + count])
    # Decode the type_id int to find where the 0x00 marker is
    _, tid_bytes = decode_uint(bytes(msg_body))  # rough: type_id is encoded as int
    marker_offset = tid_bytes
    msg_body[marker_offset] = 0x01  # corrupt the singleton marker
    corrupted = view[:msg_body_start] + bytes(msg_body) + view[msg_body_start + count:]
    dec = Decoder(io.BytesIO(corrupted))
    with pytest.raises(GobDecodeError, match="singleton marker"):
        dec.decode()


# ---------------------------------------------------------------------------
# Unknown type IDs → GobDecodeError
# ---------------------------------------------------------------------------


def test_unknown_type_id_in_value_message():
    """A value message referencing an unregistered type ID raises GobDecodeError."""
    type_id = 999  # never registered
    payload = b"\x00\x00"
    data = _make_value_message(type_id, payload)
    dec = Decoder(io.BytesIO(data))
    with pytest.raises(GobDecodeError, match="unknown type_id"):
        dec.decode()


def test_unknown_type_id_after_valid_type_def():
    """Unknown type ID is still rejected even after some valid type defs are processed."""
    from pygob.wire import FIRST_USER_ID

    # Encode a real type definition first, then a value for a different unknown type.
    buf = io.BytesIO()
    enc = Encoder(buf)
    schema = Schema("Point", X=INT, Y=INT)
    enc._emit_type_definition(schema)  # registers FIRST_USER_ID
    type_def_bytes = buf.getvalue()

    # Now append a value message for type_id=999 (not registered)
    val_msg = _make_value_message(999, b"\x00\x00")
    dec = Decoder(io.BytesIO(type_def_bytes + val_msg))
    with pytest.raises(GobDecodeError, match="unknown type_id"):
        dec.decode()


def test_unknown_field_type_id_in_struct():
    """A struct field referencing an unregistered type ID raises GobDecodeError."""
    # Encode a struct with a field that points to an unregistered nested type.
    # We craft a struct wire type whose field has type_id=888, then try to decode it.
    from pygob.codec import encode_string
    from pygob.wire import FIRST_USER_ID

    enc_buf = io.BytesIO()
    enc = Encoder(enc_buf)

    # Register a struct with a field typed as 888 (unknown).
    # We can't do this via normal Schema, so use _encode_struct_wire_type_fields directly
    # by crafting raw wire bytes. Instead, we verify via a simpler approach:
    # Decode a GobStruct with a field that claims to be type 888.

    # Build a StructWireType manually for "Bad" struct with field "X" of type 888.
    from pygob.codec import encode_int as ei
    from pygob.codec import encode_uint as eu
    from pygob.codec import encode_string as es

    def encode_struct_wire_type_raw(name: str, type_id: int, fields: list[tuple[str, int]]) -> bytes:
        """Return raw wireType bytes for a struct (StructT at WireType field 2)."""
        # CommonType: delta=1 (Name), delta=1 (Id)
        common = eu(1) + es(name) + eu(1) + ei(type_id) + eu(0)
        # Fields slice: count + each FieldType {Name, Id}
        fields_enc = eu(len(fields))
        for fname, fid in fields:
            fields_enc += eu(1) + es(fname) + eu(1) + ei(fid) + eu(0)
        # StructWireType: delta=1 (CommonType), delta=1 (Fields), terminator
        struct_wt = eu(1) + common + eu(1) + fields_enc + eu(0)
        # WireType outer: delta=3 (field 2 = StructT), StructWireType, terminator
        return eu(3) + struct_wt + eu(0)

    bad_type_id = FIRST_USER_ID
    wire_bytes = encode_struct_wire_type_raw("Bad", bad_type_id, [("X", 888)])
    type_def_msg = _make_type_def_message(bad_type_id, wire_bytes)

    # Value message: struct with field X (delta=1) having some bytes, then terminator.
    # We just need it to hit the _decode_field_from_reader path for type 888.
    struct_payload = eu(1) + eu(0) + eu(0)  # delta=1, a uint value (0), terminator
    val_msg = _make_value_message(bad_type_id, struct_payload)

    dec = Decoder(io.BytesIO(type_def_msg + val_msg))
    with pytest.raises(GobDecodeError, match="unknown"):
        dec.decode()


# ---------------------------------------------------------------------------
# Type mismatch on encode → GobEncodeError
# ---------------------------------------------------------------------------


def test_type_mismatch_int_field_string():
    """Encoding a string for an int field raises GobEncodeError."""
    schema = Schema("T", X=INT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="int"):
        enc.encode({"X": "not-an-int"}, schema=schema)


def test_type_mismatch_int_field_float():
    """Encoding a float for an int field raises GobEncodeError."""
    schema = Schema("T", X=INT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="int"):
        enc.encode({"X": 3.14}, schema=schema)


def test_type_mismatch_uint_field_string():
    """Encoding a string for a uint field raises GobEncodeError."""
    schema = Schema("T", X=UINT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="uint"):
        enc.encode({"X": "bad"}, schema=schema)


def test_type_mismatch_uint_field_negative():
    """Encoding a negative int for a uint field raises GobEncodeError."""
    schema = Schema("T", X=UINT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="non-negative"):
        enc.encode({"X": -1}, schema=schema)


def test_type_mismatch_float_field_string():
    """Encoding a string for a float field raises GobEncodeError."""
    schema = Schema("T", V=FLOAT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="float"):
        enc.encode({"V": "not-a-float"}, schema=schema)


def test_type_mismatch_string_field_int():
    """Encoding an int for a string field raises GobEncodeError."""
    schema = Schema("T", Name=STRING)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="str"):
        enc.encode({"Name": 42}, schema=schema)


def test_type_mismatch_bytes_field_string():
    """Encoding a str for a bytes field raises GobEncodeError."""
    schema = Schema("T", Data=BYTES)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="bytes"):
        enc.encode({"Data": "not-bytes"}, schema=schema)


def test_type_mismatch_bool_field_string():
    """Encoding a string for a bool field raises GobEncodeError."""
    schema = Schema("T", Flag=BOOL)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="bool"):
        enc.encode({"Flag": "yes"}, schema=schema)


def test_type_mismatch_complex_field_string():
    """Encoding a string for a complex field raises GobEncodeError."""
    schema = Schema("T", Z=COMPLEX)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="complex"):
        enc.encode({"Z": "1+2j"}, schema=schema)


def test_type_mismatch_nested_struct_field_scalar():
    """Encoding a scalar for a nested struct field raises GobEncodeError."""
    inner_schema = Schema("Inner", V=INT)
    outer_schema = Schema("Outer", Child=inner_schema)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="struct field"):
        enc.encode({"Child": 42}, schema=outer_schema)


def test_type_mismatch_nested_struct_field_string():
    """Encoding a string for a nested struct field raises GobEncodeError."""
    inner_schema = Schema("Inner", V=INT)
    outer_schema = Schema("Outer", Child=inner_schema)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="struct field"):
        enc.encode({"Child": "not-a-struct"}, schema=outer_schema)


# ---------------------------------------------------------------------------
# Missing required registrations → GobEncodeError
# ---------------------------------------------------------------------------


def test_encode_unsupported_type_raises():
    """Encoding an unsupported Python type (e.g. set) raises GobEncodeError."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="unsupported type"):
        enc.encode({1, 2, 3})


def test_encode_schema_requires_dict_or_gobstruct():
    """Encoding with a schema and a non-dict/GobStruct value raises GobEncodeError."""
    schema = Schema("Point", X=INT, Y=INT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="dict"):
        enc.encode("not-a-dict", schema=schema)


def test_encode_empty_list_without_elem_type_raises():
    """Encoding an empty list without elem_type raises GobEncodeError."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="elem_type"):
        enc.encode([])


def test_encode_empty_dict_without_types_raises():
    """Encoding an empty dict without key_type/elem_type raises GobEncodeError."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="key_type"):
        enc.encode({})


def test_encode_gob_encoded_without_registered_codec_raises():
    """Encoding a GobEncoded-typed value without a registered codec raises GobEncodeError."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="no encoder registered"):
        enc.encode_gob_encoded("raw python value", type_name="time.Time")


def test_encode_interface_field_unregistered_type_raises():
    """Encoding an interface field for a type not in any registry raises GobEncodeError.

    Note: @gobstruct-decorated classes are auto-registered and do NOT raise.
    This test uses a GobStruct with a unique type name that is in neither
    encoder.register() nor the @gobstruct global registry.
    """
    from pygob.types import GobStruct

    inner_schema = Schema("Container", Item=__import__("pygob.wire", fromlist=["INTERFACE"]).INTERFACE)
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc._emit_type_definition(inner_schema)

    # A GobStruct with a name that has no @gobstruct registration and no register() call.
    unregistered = GobStruct("TrulyUnregisteredType_XYZ", Schema("TrulyUnregisteredType_XYZ", V=INT), V=1)
    with pytest.raises(GobEncodeError, match="not registered"):
        enc._encode_struct_payload({"Item": unregistered}, inner_schema, _deferred=[])


def test_encode_nested_schema_unregistered_raises():
    """Trying to resolve a field type ID for a Schema not yet emitted raises GobEncodeError."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    inner = Schema("Inner", V=INT)
    # Do NOT call _emit_type_definition(inner) — it should raise
    with pytest.raises(GobEncodeError, match="nested schema"):
        enc._resolve_field_type_id(inner)


# ---------------------------------------------------------------------------
# Validate that valid types still work (non-regression)
# ---------------------------------------------------------------------------


def test_valid_int_field_with_bool():
    """A bool value (True/False) is accepted for an int field (bool is int in Python)."""
    schema = Schema("T", X=INT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"X": True}, schema=schema)  # True == 1
    result = Decoder(io.BytesIO(buf.getvalue())).decode()
    assert result["X"] == 1


def test_valid_float_field_with_int():
    """An int value is accepted for a float field (widening coercion)."""
    schema = Schema("T", V=FLOAT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"V": 3}, schema=schema)
    result = Decoder(io.BytesIO(buf.getvalue())).decode()
    assert result["V"] == 3.0


def test_valid_complex_field_with_int():
    """An int value is accepted for a complex field."""
    schema = Schema("T", Z=COMPLEX)
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"Z": 2}, schema=schema)
    result = Decoder(io.BytesIO(buf.getvalue())).decode()
    assert result["Z"] == 2 + 0j


def test_valid_bytes_field_with_bytearray():
    """A bytearray value is accepted for a bytes field."""
    schema = Schema("T", Data=BYTES)
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"Data": bytearray(b"hello")}, schema=schema)
    result = Decoder(io.BytesIO(buf.getvalue())).decode()
    assert result["Data"] == b"hello"


# ---------------------------------------------------------------------------
# Encoder gaps: interface _deferred, SemanticType, array_length mismatch
# ---------------------------------------------------------------------------


def test_encode_struct_payload_without_deferred_for_interface_raises():
    """_encode_struct_payload with a non-nil INTERFACE field and no _deferred raises GobEncodeError.

    The caller is responsible for passing _deferred=[]; calling the private method
    directly without it should produce a clear error rather than silently failing.
    """
    from pygob.types import GobStruct
    from pygob.wire import INTERFACE

    point_schema = Schema("Point", X=INT, Y=INT)
    container_schema = Schema("Container", Value=INTERFACE)
    point = GobStruct("Point", point_schema, X=1, Y=2)

    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="_deferred"):
        enc._encode_struct_payload({"Value": point}, container_schema)
        # _deferred defaults to None — should raise before trying to encode the interface field


def test_encode_list_array_length_mismatch_raises():
    """encode(list, array_length=N) raises GobEncodeError when len(list) != N."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    with pytest.raises(GobEncodeError, match="array_length"):
        enc.encode([1, 2], array_length=3)  # 2 elements but declared length 3


def test_encode_list_array_length_exact_does_not_raise():
    """encode(list, array_length=N) succeeds when len(list) == N."""
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode([1, 2, 3], array_length=3)  # exactly 3 elements, matches array_length


# ---------------------------------------------------------------------------
# Decoder gaps: struct field index out of range
# ---------------------------------------------------------------------------


def test_decode_struct_field_index_out_of_range():
    """A struct payload with a delta that pushes field_num beyond the struct's
    field count raises GobDecodeError."""
    from pygob.codec import encode_int as ei, encode_uint as eu

    buf = io.BytesIO()
    enc = Encoder(buf)
    schema = Schema("Point", X=INT, Y=INT)  # 2 fields: index 0 and 1
    type_id = enc._emit_type_definition(schema)
    type_def_bytes = buf.getvalue()

    # delta=5 → field_num = -1 + 5 = 4, which is >= 2 (out of range)
    struct_payload = eu(5) + ei(99) + eu(0)  # delta=5, a dummy value, terminator
    val_msg = _make_value_message(type_id, struct_payload)

    dec = Decoder(io.BytesIO(type_def_bytes + val_msg))
    with pytest.raises(GobDecodeError, match="out of range"):
        dec.decode()
