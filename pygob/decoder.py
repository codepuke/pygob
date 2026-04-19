"""Stream-oriented gob decoder: reads type definitions and values from a binary stream."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Any, BinaryIO, Callable

if TYPE_CHECKING:
    from pygob.codecs import Codec

from pygob.codec import (
    CodecReader,
    decode_bool,
    decode_bytes,
    decode_complex,
    decode_float,
    decode_int,
    decode_string,
    decode_uint,
)
from pygob.exceptions import GobDecodeError
from pygob.types import ArrayOf, GobEncoded, GobStruct, MapOf, Schema, SliceOf
from pygob.wire import (
    ARRAY_TYPE,
    BOOL,
    BYTES,
    COMMON_TYPE,
    COMPLEX,
    FIELD_TYPE,
    FIELD_TYPE_SLICE,
    FLOAT,
    INT,
    INTERFACE,
    MAP_TYPE,
    SLICE_TYPE,
    STRING,
    STRUCT_TYPE,
    UINT,
    WIRE_TYPE,
    StructWireType,
    WireType,
    decode_wire_type,
)


class Decoder:
    """Stream-oriented gob decoder.

    Reads a sequence of framed messages from *stream*.  Each message is
    either a type definition (which extends the internal type registry) or a
    value (which can be decoded once the type is known).

    Usage::

        with open("data.gob", "rb") as f:
            dec = Decoder(f)
            value = dec.decode()

        # With built-in codecs for common Go types (time.Time, UUID):
        import pygob
        dec = pygob.Decoder(f, codecs=pygob.DEFAULT_CODECS)
    """

    def __init__(
        self,
        stream: BinaryIO,
        *,
        codecs: "dict[str, Codec] | None" = None,
    ) -> None:
        self._stream = stream
        # Bootstrap type IDs predefined by the gob protocol.  We store None
        # for them because they are handled by the scalar decode paths rather
        # than via WireType objects.
        self._type_registry: dict[int, WireType | None] = {
            BOOL: None,
            INT: None,
            UINT: None,
            FLOAT: None,
            BYTES: None,
            STRING: None,
            COMPLEX: None,
            INTERFACE: None,
            WIRE_TYPE: None,
            ARRAY_TYPE: None,
            COMMON_TYPE: None,
            SLICE_TYPE: None,
            STRUCT_TYPE: None,
            FIELD_TYPE: None,
            FIELD_TYPE_SLICE: None,
            MAP_TYPE: None,
        }
        # Name→schema registry for interface value decoding.
        self._name_registry: dict[str, Any] = {}
        # Name→decode_fn registry for GobEncoder/BinaryMarshaler/TextMarshaler types.
        self._codec_registry: dict[str, Callable[[bytes], Any]] = {}
        if codecs:
            for type_name, codec in codecs.items():
                self._codec_registry[type_name] = codec.decode

    def register(self, name: str, schema: Any) -> None:
        """Register a concrete type name for interface value decoding.

        Note: for Go→Python decoding, calling this method is **not required**.
        The gob wire format embeds inline type definitions inside every
        interface-value payload, making the stream fully self-describing.
        This method is kept for Python→Python round-trips where the encoder
        side requires schema information.

        Args:
            name: The Go type name as registered with ``gob.Register``.
            schema: A Schema object describing the type's fields.
        """
        self._name_registry[name] = schema

    def register_codec(self, type_name: str, decode_fn: Callable[[bytes], Any]) -> None:
        """Register a custom decoder for a GobEncoder, BinaryMarshaler, or TextMarshaler type.

        When the decoder encounters a value whose wire type is one of the marshaler
        variants and its Go type name matches *type_name*, it calls *decode_fn(data)*
        instead of returning a raw ``GobEncoded`` wrapper.

        Args:
            type_name: The Go type name (e.g. ``"time.Time"``).
            decode_fn: A callable ``(bytes) -> Any`` that decodes the marshaled bytes.
        """
        self._codec_registry[type_name] = decode_fn

    def _apply_codec(self, type_name: str, data: bytes) -> Any:
        """Return decoded value for a marshaler type, using a registered codec if available."""
        if type_name in self._codec_registry:
            return self._codec_registry[type_name](data)
        return GobEncoded(type_name, data)

    def _read_message(self) -> tuple[int, bytes]:
        """Read one framed message from the stream.

        The gob stream format is ``(byteCount message)*``.  Each message
        begins with a signed integer type-id:

        * Negative type-id → type definition (the actual id is ``-type_id``).
        * Positive type-id → value of that type.

        Returns:
            A ``(type_id, payload)`` tuple where *type_id* is the signed
            integer read from the message header and *payload* is the
            remaining bytes of the message (the wireType or encoded value).

        Raises:
            GobDecodeError: on truncated or malformed input.
        """
        reader = CodecReader(self._stream)
        try:
            byte_count = reader.read_uint()
        except GobDecodeError as exc:
            raise GobDecodeError(f"_read_message: failed to read byte count: {exc}") from exc

        raw = reader.read_raw(byte_count)

        type_id, consumed = decode_int(raw)
        payload = raw[consumed:]
        return type_id, payload

    def _process_type_definition(self, type_id: int, payload: bytes) -> None:
        """Decode a wireType from *payload* and register it under *type_id*.

        Args:
            type_id: The positive type identifier assigned to this type
                (i.e. ``-raw_type_id`` where ``raw_type_id`` is the negative
                value read from the stream header).
            payload: The bytes of the wireType struct encoding.

        Raises:
            GobDecodeError: if *payload* cannot be decoded as a wireType.
        """
        reader = CodecReader(BytesIO(payload))
        wt = decode_wire_type(reader)
        self._type_registry[type_id] = wt

    def decode(self) -> Any:
        """Decode the next value from the stream.

        Reads framed messages until a value message is encountered, processing
        any interleaved type definitions.  Returns the decoded Python value.

        Raises:
            GobDecodeError: if the stream is malformed or a type is unknown.
        """
        while True:
            type_id, payload = self._read_message()
            if type_id < 0:
                self._process_type_definition(-type_id, payload)
            else:
                return self._decode_value(type_id, payload)

    def _decode_value(self, type_id: int, payload: bytes) -> Any:
        """Dispatch value decoding based on *type_id*.

        Args:
            type_id: Positive integer identifying the gob type.
            payload: Raw bytes of the encoded value (including any wrapper).

        Raises:
            GobDecodeError: for unknown or unsupported type IDs.
        """
        if type_id == BOOL:
            return self._unwrap_scalar(payload, decode_bool)
        if type_id == INT:
            return self._unwrap_scalar(payload, decode_int)
        if type_id == UINT:
            return self._unwrap_scalar(payload, decode_uint)
        if type_id == FLOAT:
            return self._unwrap_scalar(payload, decode_float)
        if type_id == BYTES:
            return self._unwrap_scalar(payload, decode_bytes)
        if type_id == STRING:
            return self._unwrap_scalar(payload, decode_string)
        if type_id == COMPLEX:
            return self._unwrap_scalar(payload, decode_complex)

        wt = self._type_registry.get(type_id)
        if wt is None:
            raise GobDecodeError(f"unknown type_id {type_id}")
        if wt.struct_t is not None:
            reader = CodecReader(BytesIO(payload))
            return self._decode_struct_from_reader(wt.struct_t, reader)
        # Slices, arrays, and maps are singleton-wrapped like scalars.
        if not payload or payload[0] != 0x00:
            raise GobDecodeError(
                f"collection payload for type_id {type_id} missing 0x00 singleton marker"
            )
        reader = CodecReader(BytesIO(payload[1:]))
        if wt.slice_t is not None:
            return self._decode_list_from_reader(wt.slice_t.elem, reader)
        if wt.array_t is not None:
            return self._decode_list_from_reader(wt.array_t.elem, reader)
        if wt.map_t is not None:
            return self._decode_map_from_reader(wt.map_t.key, wt.map_t.elem, reader)
        if (
            wt.gob_encoder_t is not None
            or wt.binary_marshaler_t is not None
            or wt.text_marshaler_t is not None
        ):
            length = reader.read_uint()
            data = reader.read_raw(length)
            return self._apply_codec(wt.common.name, data)
        raise GobDecodeError(f"unsupported wire type for type_id {type_id}")

    def _decode_struct_from_reader(self, struct_t: StructWireType, reader: CodecReader) -> GobStruct:
        """Decode a struct value from *reader*, building a GobStruct.

        Reads delta-encoded field numbers until a zero delta terminates the
        struct.  Fields not present in the stream get Python zero values.

        Args:
            struct_t: The StructWireType describing this struct's fields.
            reader: A CodecReader positioned at the start of the struct encoding.

        Returns:
            A GobStruct with all fields populated.
        """
        # Pre-populate all fields with zero values (handles omitted zero fields)
        fields: dict[str, Any] = {
            f.name: self._zero_value_for(f.id) for f in struct_t.fields
        }

        field_num = -1
        while True:
            try:
                delta = reader.read_uint()
            except GobDecodeError:
                # EOF before explicit delta=0 terminator: happens when an
                # interface field's inline type def consumes the last bytes of
                # the payload.  Treat as struct terminator.
                break
            if delta == 0:
                break
            field_num += delta
            if field_num >= len(struct_t.fields):
                raise GobDecodeError(
                    f"field index {field_num} out of range for struct "
                    f"{struct_t.common.name!r} ({len(struct_t.fields)} fields)"
                )
            field_wt = struct_t.fields[field_num]
            fields[field_wt.name] = self._decode_field_from_reader(field_wt.id, reader)

        schema = self._build_schema_from_struct(struct_t)
        return GobStruct(struct_t.common.name, schema, **fields)

    def _decode_field_from_reader(self, type_id: int, reader: CodecReader) -> Any:
        """Decode a single field value of *type_id* directly from *reader*.

        Args:
            type_id: The gob type ID for this field.
            reader: A CodecReader positioned at the field's encoded bytes.

        Raises:
            GobDecodeError: for unknown or unsupported type IDs.
        """
        if type_id == BOOL:
            return reader.read_bool()
        if type_id == INT:
            return reader.read_int()
        if type_id == UINT:
            return reader.read_uint()
        if type_id == FLOAT:
            return reader.read_float()
        if type_id == BYTES:
            return reader.read_bytes_value()
        if type_id == STRING:
            return reader.read_string()
        if type_id == COMPLEX:
            return reader.read_complex()
        if type_id == INTERFACE:
            return self._decode_interface_from_reader(reader)

        wt = self._type_registry.get(type_id)
        if wt is None:
            raise GobDecodeError(f"unknown field type_id {type_id}")
        if wt.struct_t is not None:
            return self._decode_struct_from_reader(wt.struct_t, reader)
        if wt.slice_t is not None:
            return self._decode_list_from_reader(wt.slice_t.elem, reader)
        if wt.array_t is not None:
            return self._decode_list_from_reader(wt.array_t.elem, reader)
        if wt.map_t is not None:
            return self._decode_map_from_reader(wt.map_t.key, wt.map_t.elem, reader)
        if (
            wt.gob_encoder_t is not None
            or wt.binary_marshaler_t is not None
            or wt.text_marshaler_t is not None
        ):
            length = reader.read_uint()
            data = reader.read_raw(length)
            return self._apply_codec(wt.common.name, data)
        raise GobDecodeError(f"unsupported field wire type for type_id {type_id}")

    def _decode_interface_from_reader(self, reader: CodecReader) -> Any:
        """Decode an interface value whose field encoding starts at *reader*.

        Go gob encodes a non-nil interface field as:
        1. Type name string (empty string → nil interface).
        2. Zero or more inline type-definition bytes embedded directly in the
           current struct payload — each is a signed type-id (negative) followed
           by the wireType bytes, with no outer byte-count framing.
        3. The concrete *value* comes as a separate message on the outer stream,
           read via :meth:`decode`.

        The concrete value message payload uses a byte-count wrapper:
        ``uint_N  struct_bytes(N)`` (with a trailing 0x00 which is ignored).

        Args:
            reader: CodecReader positioned at the start of the interface field
                    (i.e. just after the field's delta byte in the outer struct).

        Returns:
            The decoded concrete Python value, or ``None`` for a nil interface.
        """
        type_name = reader.read_string()
        if not type_name:
            return None

        # Consume inline type definitions embedded in the current payload.
        # Each def is: signed_type_id (negative) + wireType bytes.
        # We stop when the reader is exhausted (EOF).
        while True:
            try:
                raw_id = reader.read_int()
            except GobDecodeError:
                break  # EOF — all inline type defs consumed
            if raw_id == 0:
                break
            if raw_id < 0:
                actual_id = -raw_id
                wt = decode_wire_type(reader)
                self._type_registry[actual_id] = wt

        # The concrete value arrives as the next value message in the outer stream.
        while True:
            type_id, payload = self._read_message()
            if type_id < 0:
                self._process_type_definition(-type_id, payload)
            else:
                return self._decode_interface_concrete_value(type_id, payload)

    def _decode_interface_concrete_value(self, type_id: int, payload: bytes) -> Any:
        """Decode the concrete value payload of an interface value message.

        Interface concrete value messages have a byte-count-wrapped payload:
        ``uint_N  struct_bytes(N)`` optionally followed by a trailing 0x00.
        This differs from regular top-level struct messages.

        Args:
            type_id: The gob type ID of the concrete type.
            payload: The raw payload bytes from the value message.

        Returns:
            The decoded Python value.
        """
        wt = self._type_registry.get(type_id)
        if wt is None:
            raise GobDecodeError(
                f"unknown type_id {type_id} for interface concrete value"
            )
        if wt.struct_t is not None:
            reader = CodecReader(BytesIO(payload))
            byte_count = reader.read_uint()
            struct_bytes = reader.read_raw(byte_count)
            return self._decode_struct_from_reader(
                wt.struct_t, CodecReader(BytesIO(struct_bytes))
            )
        # For non-struct concrete types, fall back to standard decoding.
        return self._decode_value(type_id, payload)

    def _zero_value_for(self, type_id: int) -> Any:
        """Return the Python zero value corresponding to a gob type ID.

        Args:
            type_id: A gob type ID (bootstrap or user-defined).

        Returns:
            The appropriate Python zero value for the type.
        """
        if type_id == BOOL:
            return False
        if type_id in (INT, UINT):
            return 0
        if type_id == FLOAT:
            return 0.0
        if type_id == STRING:
            return ""
        if type_id == BYTES:
            return b""
        if type_id == COMPLEX:
            return 0 + 0j
        wt = self._type_registry.get(type_id)
        if wt is not None:
            if wt.slice_t is not None or wt.array_t is not None:
                return []
            if wt.map_t is not None:
                return {}
        # For user-defined struct types (and unknown types), use None as placeholder.
        return None

    def _decode_list_from_reader(self, elem_type_id: int, reader: CodecReader) -> list:
        """Decode a slice or array value from *reader*.

        Reads a uint count, then decodes *count* elements of *elem_type_id*.

        Args:
            elem_type_id: The gob type ID of each element.
            reader: A CodecReader positioned at the start of the collection encoding.

        Returns:
            A Python list of decoded elements.
        """
        count = reader.read_uint()
        return [self._decode_field_from_reader(elem_type_id, reader) for _ in range(count)]

    def _decode_map_from_reader(
        self, key_type_id: int, elem_type_id: int, reader: CodecReader
    ) -> dict:
        """Decode a map value from *reader*.

        Reads a uint count, then decodes *count* (key, value) pairs.

        Args:
            key_type_id: The gob type ID of each key.
            elem_type_id: The gob type ID of each value.
            reader: A CodecReader positioned at the start of the map encoding.

        Returns:
            A Python dict of decoded key-value pairs.
        """
        count = reader.read_uint()
        result: dict = {}
        for _ in range(count):
            key = self._decode_field_from_reader(key_type_id, reader)
            value = self._decode_field_from_reader(elem_type_id, reader)
            result[key] = value
        return result

    def _build_schema_from_struct(self, struct_t: StructWireType) -> Schema:
        """Build a Schema from a StructWireType for use in a GobStruct.

        Args:
            struct_t: The wire type to convert.

        Returns:
            A Schema capturing the struct's name and field type descriptors.
        """
        field_types: dict[str, Any] = {}
        for f in struct_t.fields:
            field_types[f.name] = self._schema_for_type_id(f.id)
        return Schema(struct_t.common.name, **field_types)

    def _schema_for_type_id(self, type_id: int) -> Any:
        """Return a field type descriptor for *type_id*.

        Returns bootstrap type IDs for primitives, a ``Schema`` for struct
        types, and collection descriptors (``SliceOf``, ``MapOf``,
        ``ArrayOf``) for collection types.  This ensures that round-tripped
        ``GobStruct`` values carry fully self-describing schemas.
        """
        if type_id in (BOOL, INT, UINT, FLOAT, BYTES, STRING, COMPLEX):
            return type_id
        wt = self._type_registry.get(type_id)
        if wt is not None:
            if wt.struct_t is not None:
                return self._build_schema_from_struct(wt.struct_t)
            if wt.slice_t is not None:
                return SliceOf(self._schema_for_type_id(wt.slice_t.elem))
            if wt.array_t is not None:
                return ArrayOf(
                    self._schema_for_type_id(wt.array_t.elem), wt.array_t.len
                )
            if wt.map_t is not None:
                return MapOf(
                    self._schema_for_type_id(wt.map_t.key),
                    self._schema_for_type_id(wt.map_t.elem),
                )
        return type_id

    @staticmethod
    def _unwrap_scalar(payload: bytes, decode_fn) -> Any:
        """Decode a singleton-wrapped scalar from *payload*.

        Non-struct top-level values are wrapped: the first byte is ``0x00``
        (the singleton field marker), followed by the encoded value bytes.
        There is no explicit struct terminator — message framing via the outer
        byte-count field handles stream boundaries.

        Args:
            payload: Bytes starting with the ``0x00`` singleton marker.
            decode_fn: One of the ``decode_*`` functions from ``pygob.codec``.

        Returns:
            The decoded Python scalar.

        Raises:
            GobDecodeError: if the leading singleton marker is missing.
        """
        if not payload or payload[0] != 0x00:
            raise GobDecodeError(
                "scalar payload missing leading 0x00 singleton marker"
            )
        value, _ = decode_fn(payload[1:])
        return value
