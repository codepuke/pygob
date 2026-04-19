"""Wire type definitions, bootstrap type IDs, and wireType struct decoding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pygob.codec import CodecReader

# ---------------------------------------------------------------------------
# Bootstrap type IDs — predefined by the gob protocol
# ---------------------------------------------------------------------------

BOOL = 1
INT = 2
UINT = 3
FLOAT = 4
BYTES = 5
STRING = 6
COMPLEX = 7
INTERFACE = 8

WIRE_TYPE = 16
ARRAY_TYPE = 17
COMMON_TYPE = 18
SLICE_TYPE = 19
STRUCT_TYPE = 20
FIELD_TYPE = 21
FIELD_TYPE_SLICE = 22
MAP_TYPE = 23

FIRST_USER_ID = 65

# ---------------------------------------------------------------------------
# Wire type dataclasses — represent decoded type definitions from the stream
# ---------------------------------------------------------------------------


@dataclass
class CommonType:
    """Embedded in every wire type; carries the Go type name and assigned ID."""

    name: str = ""
    id: int = 0


@dataclass
class FieldWireType:
    """One field in a StructWireType."""

    name: str = ""
    id: int = 0  # type ID of this field's type


@dataclass
class ArrayWireType:
    """Wire representation of a Go array type."""

    common: CommonType = field(default_factory=CommonType)
    elem: int = 0  # element type ID
    len: int = 0   # fixed length


@dataclass
class SliceWireType:
    """Wire representation of a Go slice type."""

    common: CommonType = field(default_factory=CommonType)
    elem: int = 0  # element type ID


@dataclass
class StructWireType:
    """Wire representation of a Go struct type."""

    common: CommonType = field(default_factory=CommonType)
    fields: list[FieldWireType] = field(default_factory=list)


@dataclass
class MapWireType:
    """Wire representation of a Go map type."""

    common: CommonType = field(default_factory=CommonType)
    key: int = 0   # key type ID
    elem: int = 0  # element type ID


@dataclass
class GobEncoderWireType:
    """Wire representation for types implementing GobEncoder, BinaryMarshaler, or TextMarshaler."""

    common: CommonType = field(default_factory=CommonType)


@dataclass
class WireType:
    """Union container for all wire type variants (mirrors Go's wireType struct).

    Exactly one of the variant fields should be set (non-None) for a valid
    type definition.  Field positions correspond to gob struct field numbers:
      0 = array, 1 = slice, 2 = struct, 3 = map,
      4 = gob_encoder, 5 = binary_marshaler, 6 = text_marshaler
    """

    array_t: ArrayWireType | None = None
    slice_t: SliceWireType | None = None
    struct_t: StructWireType | None = None
    map_t: MapWireType | None = None
    gob_encoder_t: GobEncoderWireType | None = None
    binary_marshaler_t: GobEncoderWireType | None = None
    text_marshaler_t: GobEncoderWireType | None = None

    @property
    def common(self) -> CommonType:
        """Return the CommonType of whichever variant is set."""
        for v in (
            self.array_t,
            self.slice_t,
            self.struct_t,
            self.map_t,
            self.gob_encoder_t,
            self.binary_marshaler_t,
            self.text_marshaler_t,
        ):
            if v is not None:
                return v.common
        raise ValueError("WireType has no variant set")


# ---------------------------------------------------------------------------
# Wire type decoding — reads a wireType struct from a CodecReader stream
# ---------------------------------------------------------------------------


def _decode_common_type(reader: "CodecReader") -> CommonType:
    """Decode a CommonType struct (Name string, Id typeId) from the stream."""
    ct = CommonType()
    field_num = -1
    while True:
        delta = reader.read_uint()
        if delta == 0:
            break
        field_num += delta
        if field_num == 0:
            ct.name = reader.read_string()
        elif field_num == 1:
            ct.id = reader.read_int()
    return ct


def _decode_field_wire_type(reader: "CodecReader") -> FieldWireType:
    """Decode one FieldWireType struct (Name string, Id typeId) from the stream."""
    ft = FieldWireType()
    field_num = -1
    while True:
        delta = reader.read_uint()
        if delta == 0:
            break
        field_num += delta
        if field_num == 0:
            ft.name = reader.read_string()
        elif field_num == 1:
            ft.id = reader.read_int()
    return ft


def _decode_array_wire_type(reader: "CodecReader") -> ArrayWireType:
    """Decode an ArrayWireType struct from the stream."""
    awt = ArrayWireType()
    field_num = -1
    while True:
        delta = reader.read_uint()
        if delta == 0:
            break
        field_num += delta
        if field_num == 0:
            awt.common = _decode_common_type(reader)
        elif field_num == 1:
            awt.elem = reader.read_int()
        elif field_num == 2:
            awt.len = reader.read_int()
    return awt


def _decode_slice_wire_type(reader: "CodecReader") -> SliceWireType:
    """Decode a SliceWireType struct from the stream."""
    swt = SliceWireType()
    field_num = -1
    while True:
        delta = reader.read_uint()
        if delta == 0:
            break
        field_num += delta
        if field_num == 0:
            swt.common = _decode_common_type(reader)
        elif field_num == 1:
            swt.elem = reader.read_int()
    return swt


def _decode_struct_wire_type(reader: "CodecReader") -> StructWireType:
    """Decode a StructWireType struct from the stream."""
    swt = StructWireType()
    field_num = -1
    while True:
        delta = reader.read_uint()
        if delta == 0:
            break
        field_num += delta
        if field_num == 0:
            swt.common = _decode_common_type(reader)
        elif field_num == 1:
            count = reader.read_uint()
            swt.fields = [_decode_field_wire_type(reader) for _ in range(count)]
    return swt


def _decode_map_wire_type(reader: "CodecReader") -> MapWireType:
    """Decode a MapWireType struct from the stream."""
    mwt = MapWireType()
    field_num = -1
    while True:
        delta = reader.read_uint()
        if delta == 0:
            break
        field_num += delta
        if field_num == 0:
            mwt.common = _decode_common_type(reader)
        elif field_num == 1:
            mwt.key = reader.read_int()
        elif field_num == 2:
            mwt.elem = reader.read_int()
    return mwt


def _decode_gob_encoder_wire_type(reader: "CodecReader") -> GobEncoderWireType:
    """Decode a GobEncoderWireType struct (used for all three marshaler variants)."""
    gt = GobEncoderWireType()
    field_num = -1
    while True:
        delta = reader.read_uint()
        if delta == 0:
            break
        field_num += delta
        if field_num == 0:
            gt.common = _decode_common_type(reader)
    return gt


def decode_wire_type(reader: "CodecReader") -> WireType:
    """Decode a wireType struct value from *reader*.

    The reader must be positioned at the start of the wireType struct encoding
    (immediately after the type-ID field in a type-definition message).

    Dispatches on the delta-encoded field number to produce the appropriate
    variant (ArrayWireType, SliceWireType, StructWireType, MapWireType, or
    GobEncoderWireType).
    """
    wt = WireType()
    field_num = -1
    while True:
        delta = reader.read_uint()
        if delta == 0:
            break
        field_num += delta
        if field_num == 0:
            wt.array_t = _decode_array_wire_type(reader)
        elif field_num == 1:
            wt.slice_t = _decode_slice_wire_type(reader)
        elif field_num == 2:
            wt.struct_t = _decode_struct_wire_type(reader)
        elif field_num == 3:
            wt.map_t = _decode_map_wire_type(reader)
        elif field_num == 4:
            wt.gob_encoder_t = _decode_gob_encoder_wire_type(reader)
        elif field_num == 5:
            wt.binary_marshaler_t = _decode_gob_encoder_wire_type(reader)
        elif field_num == 6:
            wt.text_marshaler_t = _decode_gob_encoder_wire_type(reader)
    return wt
