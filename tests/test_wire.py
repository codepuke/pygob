"""Tests for pygob/wire.py — bootstrap type IDs, wire type dataclasses, and decode_wire_type."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from pygob.codec import CodecReader, decode_int, decode_uint
from pygob.wire import (
    ARRAY_TYPE,
    BOOL,
    BYTES,
    COMMON_TYPE,
    COMPLEX,
    FIELD_TYPE,
    FIELD_TYPE_SLICE,
    FIRST_USER_ID,
    FLOAT,
    INT,
    INTERFACE,
    MAP_TYPE,
    SLICE_TYPE,
    STRING,
    STRUCT_TYPE,
    UINT,
    WIRE_TYPE,
    ArrayWireType,
    CommonType,
    FieldWireType,
    FLOAT,
    GobEncoderWireType,
    INT,
    MapWireType,
    SliceWireType,
    STRING,
    StructWireType,
    UINT,
    WireType,
    decode_wire_type,
)


# ---------------------------------------------------------------------------
# Bootstrap type ID constants
# ---------------------------------------------------------------------------


class TestBootstrapTypeIds:
    def test_scalar_ids(self):
        assert BOOL == 1
        assert INT == 2
        assert UINT == 3
        assert FLOAT == 4
        assert BYTES == 5
        assert STRING == 6
        assert COMPLEX == 7
        assert INTERFACE == 8

    def test_wire_type_ids(self):
        assert WIRE_TYPE == 16
        assert ARRAY_TYPE == 17
        assert COMMON_TYPE == 18
        assert SLICE_TYPE == 19
        assert STRUCT_TYPE == 20
        assert FIELD_TYPE == 21
        assert FIELD_TYPE_SLICE == 22
        assert MAP_TYPE == 23

    def test_first_user_id(self):
        assert FIRST_USER_ID == 65


# ---------------------------------------------------------------------------
# Dataclass construction and defaults
# ---------------------------------------------------------------------------


class TestCommonType:
    def test_defaults(self):
        ct = CommonType()
        assert ct.name == ""
        assert ct.id == 0

    def test_with_values(self):
        ct = CommonType(name="Point", id=65)
        assert ct.name == "Point"
        assert ct.id == 65


class TestFieldWireType:
    def test_defaults(self):
        ft = FieldWireType()
        assert ft.name == ""
        assert ft.id == 0

    def test_with_values(self):
        ft = FieldWireType(name="X", id=INT)
        assert ft.name == "X"
        assert ft.id == INT


class TestArrayWireType:
    def test_defaults(self):
        awt = ArrayWireType()
        assert awt.common == CommonType()
        assert awt.elem == 0
        assert awt.len == 0

    def test_with_values(self):
        awt = ArrayWireType(common=CommonType("IntArray", 70), elem=INT, len=3)
        assert awt.common.name == "IntArray"
        assert awt.elem == INT
        assert awt.len == 3


class TestSliceWireType:
    def test_defaults(self):
        swt = SliceWireType()
        assert swt.common == CommonType()
        assert swt.elem == 0

    def test_with_values(self):
        swt = SliceWireType(common=CommonType("[]int", 66), elem=INT)
        assert swt.elem == INT


class TestStructWireType:
    def test_defaults(self):
        swt = StructWireType()
        assert swt.common == CommonType()
        assert swt.fields == []

    def test_with_fields(self):
        fields = [FieldWireType("X", INT), FieldWireType("Y", INT)]
        swt = StructWireType(common=CommonType("Point", 65), fields=fields)
        assert len(swt.fields) == 2
        assert swt.fields[0].name == "X"
        assert swt.fields[1].name == "Y"

    def test_fields_are_independent(self):
        # Ensure default_factory gives each instance its own list
        a = StructWireType()
        b = StructWireType()
        a.fields.append(FieldWireType("Z", INT))
        assert b.fields == []


class TestMapWireType:
    def test_defaults(self):
        mwt = MapWireType()
        assert mwt.common == CommonType()
        assert mwt.key == 0
        assert mwt.elem == 0

    def test_with_values(self):
        mwt = MapWireType(common=CommonType("map[string]int", 67), key=STRING, elem=INT)
        assert mwt.key == STRING
        assert mwt.elem == INT


class TestGobEncoderWireType:
    def test_defaults(self):
        g = GobEncoderWireType()
        assert g.common == CommonType()

    def test_with_values(self):
        g = GobEncoderWireType(common=CommonType("time.Time", 68))
        assert g.common.name == "time.Time"


class TestWireType:
    def test_defaults_all_none(self):
        wt = WireType()
        assert wt.array_t is None
        assert wt.slice_t is None
        assert wt.struct_t is None
        assert wt.map_t is None
        assert wt.gob_encoder_t is None
        assert wt.binary_marshaler_t is None
        assert wt.text_marshaler_t is None

    def test_common_struct_variant(self):
        struct_t = StructWireType(common=CommonType("Point", 65))
        wt = WireType(struct_t=struct_t)
        assert wt.common.name == "Point"
        assert wt.common.id == 65

    def test_common_slice_variant(self):
        slice_t = SliceWireType(common=CommonType("[]int", 66))
        wt = WireType(slice_t=slice_t)
        assert wt.common.name == "[]int"

    def test_common_map_variant(self):
        map_t = MapWireType(common=CommonType("map[string]int", 67))
        wt = WireType(map_t=map_t)
        assert wt.common.name == "map[string]int"

    def test_common_array_variant(self):
        array_t = ArrayWireType(common=CommonType("IntArray", 68))
        wt = WireType(array_t=array_t)
        assert wt.common.name == "IntArray"

    def test_common_gob_encoder_variant(self):
        enc_t = GobEncoderWireType(common=CommonType("time.Time", 69))
        wt = WireType(gob_encoder_t=enc_t)
        assert wt.common.name == "time.Time"

    def test_common_raises_when_no_variant(self):
        wt = WireType()
        with pytest.raises(ValueError, match="no variant set"):
            _ = wt.common


# ---------------------------------------------------------------------------
# Helpers for loading wireType bytes from Go-generated .gob files
# ---------------------------------------------------------------------------

TESTDATA = Path(__file__).parent / "testdata"


def _read_typedef_bytes(gob_file: Path, index: int = 0) -> tuple[int, bytes]:
    """Extract wireType bytes from a type-definition message in a .gob file.

    Reads the *index*-th type-definition message (0=first) and returns
    ``(type_id, wire_bytes)`` where *type_id* is the positive user type ID
    and *wire_bytes* is the wireType struct encoding ready for a CodecReader.
    """
    buf = BytesIO(gob_file.read_bytes())
    typedef_count = 0
    while True:
        # read message byte count
        count, _ = decode_uint(buf)
        msg = buf.read(count)
        msg_buf = BytesIO(msg)
        type_id_signed, _ = decode_int(msg_buf)
        if type_id_signed < 0:
            # negative → type definition; positive type id = -type_id_signed
            if typedef_count == index:
                return -type_id_signed, msg_buf.read()
            typedef_count += 1
        # else: value message — skip (already consumed)


# ---------------------------------------------------------------------------
# Tests for decode_wire_type
# ---------------------------------------------------------------------------


class TestDecodeWireType:
    """Task 4.1: decode_wire_type against Go-generated type descriptors."""

    def test_struct_simple_point(self):
        """Point struct: two int fields."""
        _, wire_bytes = _read_typedef_bytes(TESTDATA / "struct_simple.gob")
        reader = CodecReader(BytesIO(wire_bytes))
        wt = decode_wire_type(reader)

        assert wt.struct_t is not None
        assert wt.array_t is None
        assert wt.slice_t is None
        assert wt.map_t is None

        st = wt.struct_t
        assert st.common.name == "Point"
        assert len(st.fields) == 2
        assert st.fields[0].name == "X"
        assert st.fields[0].id == INT
        assert st.fields[1].name == "Y"
        assert st.fields[1].id == INT

    def test_struct_mixed(self):
        """MixedStruct: string, int, float, bool fields."""
        _, wire_bytes = _read_typedef_bytes(TESTDATA / "struct_mixed.gob")
        reader = CodecReader(BytesIO(wire_bytes))
        wt = decode_wire_type(reader)

        assert wt.struct_t is not None
        st = wt.struct_t
        assert st.common.name == "MixedStruct"
        assert len(st.fields) == 4

        by_name = {f.name: f.id for f in st.fields}
        assert by_name["Name"] == STRING
        assert by_name["Age"] == INT
        assert by_name["Score"] == FLOAT
        assert by_name["Active"] == BOOL

    def test_struct_nested_outer(self):
        """NestedStruct: first typedef in the file is the outer type."""
        _, wire_bytes = _read_typedef_bytes(TESTDATA / "struct_nested.gob", index=0)
        reader = CodecReader(BytesIO(wire_bytes))
        wt = decode_wire_type(reader)

        assert wt.struct_t is not None
        st = wt.struct_t
        assert st.common.name == "NestedStruct"
        assert len(st.fields) == 2
        assert st.fields[0].name == "Label"
        assert st.fields[0].id == STRING

        # Origin field type ID should be Point's type ID (second typedef)
        origin_type_id, _ = _read_typedef_bytes(TESTDATA / "struct_nested.gob", index=1)
        assert st.fields[1].name == "Origin"
        assert st.fields[1].id == origin_type_id

    def test_struct_nested_point(self):
        """Second typedef in struct_nested.gob is Point."""
        _, wire_bytes = _read_typedef_bytes(TESTDATA / "struct_nested.gob", index=1)
        reader = CodecReader(BytesIO(wire_bytes))
        wt = decode_wire_type(reader)

        assert wt.struct_t is not None
        assert wt.struct_t.common.name == "Point"

    def test_slice_int(self):
        """[]int slice type descriptor."""
        type_id, wire_bytes = _read_typedef_bytes(TESTDATA / "slice_int.gob")
        reader = CodecReader(BytesIO(wire_bytes))
        wt = decode_wire_type(reader)

        assert wt.slice_t is not None
        assert wt.array_t is None
        assert wt.struct_t is None

        st = wt.slice_t
        assert st.common.id == type_id
        assert st.elem == INT

    def test_slice_string(self):
        """[]string slice type descriptor."""
        _, wire_bytes = _read_typedef_bytes(TESTDATA / "slice_string.gob")
        reader = CodecReader(BytesIO(wire_bytes))
        wt = decode_wire_type(reader)

        assert wt.slice_t is not None
        assert wt.slice_t.elem == STRING

    def test_array_int(self):
        """[3]int array type descriptor."""
        type_id, wire_bytes = _read_typedef_bytes(TESTDATA / "array_int.gob")
        reader = CodecReader(BytesIO(wire_bytes))
        wt = decode_wire_type(reader)

        assert wt.array_t is not None
        assert wt.slice_t is None
        assert wt.struct_t is None

        at = wt.array_t
        assert at.common.id == type_id
        assert at.elem == INT
        assert at.len == 3

    def test_map_string_int(self):
        """map[string]int type descriptor."""
        type_id, wire_bytes = _read_typedef_bytes(TESTDATA / "map_string_int.gob")
        reader = CodecReader(BytesIO(wire_bytes))
        wt = decode_wire_type(reader)

        assert wt.map_t is not None
        assert wt.slice_t is None
        assert wt.struct_t is None

        mt = wt.map_t
        assert mt.common.id == type_id
        assert mt.key == STRING
        assert mt.elem == INT

    def test_map_int_string(self):
        """map[int]string type descriptor."""
        _, wire_bytes = _read_typedef_bytes(TESTDATA / "map_int_string.gob")
        reader = CodecReader(BytesIO(wire_bytes))
        wt = decode_wire_type(reader)

        assert wt.map_t is not None
        assert wt.map_t.key == INT
        assert wt.map_t.elem == STRING

    def test_type_id_stored_in_common(self):
        """The CommonType.id stored inside the wireType equals the message type ID."""
        type_id, wire_bytes = _read_typedef_bytes(TESTDATA / "struct_simple.gob")
        reader = CodecReader(BytesIO(wire_bytes))
        wt = decode_wire_type(reader)
        assert wt.common.id == type_id

    def test_decode_consumes_all_bytes(self):
        """decode_wire_type should consume exactly the wireType encoding, no more."""
        _, wire_bytes = _read_typedef_bytes(TESTDATA / "struct_simple.gob")
        stream = BytesIO(wire_bytes)
        reader = CodecReader(stream)
        decode_wire_type(reader)
        assert stream.read() == b"", "unexpected trailing bytes after wireType"
