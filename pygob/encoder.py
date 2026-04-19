"""Stream-oriented gob encoder: emits type definitions and values to a binary stream."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, BinaryIO, Callable

if TYPE_CHECKING:
    from pygob.codecs import Codec

from pygob.codec import (
    encode_bool,
    encode_bytes,
    encode_complex,
    encode_float,
    encode_int,
    encode_string,
    encode_uint,
)
from pygob.exceptions import GobEncodeError
from pygob.types import ArrayOf, GobEncoded, GobStruct, MapOf, Schema, SemanticType, SliceOf, UInt
from pygob.wire import BOOL, BYTES, COMPLEX, FIRST_USER_ID, FLOAT, INT, INTERFACE, STRING, UINT


class Encoder:
    """Stream-oriented gob encoder.

    Writes a sequence of framed messages to *stream*. Type definitions are
    emitted automatically on first use and cached so they are never written
    more than once per schema name.

    Usage::

        import io
        from pygob.encoder import Encoder
        from pygob.types import Schema
        from pygob.wire import INT

        buf = io.BytesIO()
        enc = Encoder(buf)
        PointSchema = Schema("Point", X=INT, Y=INT)
        type_id = enc._emit_type_definition(PointSchema)
        enc._emit_value(type_id, payload_bytes)

        # With built-in codecs for common Go types (time.Time, UUID):
        import pygob
        enc = pygob.Encoder(buf, codecs=pygob.DEFAULT_CODECS)
    """

    def __init__(
        self,
        stream: BinaryIO,
        *,
        codecs: "dict[str, Codec] | None" = None,
    ) -> None:
        self._stream = stream
        # Maps schema name → assigned type ID (for struct deduplication)
        self._schema_registry: dict[str, int] = {}
        # Maps collection key tuple → assigned type ID
        # Keys: ("slice", elem_type_id) or ("map", key_type_id, elem_type_id)
        self._collection_registry: dict[tuple, int] = {}
        self._next_id: int = FIRST_USER_ID
        # Maps schema.name → (go_name, schema) for interface concrete types
        self._interface_registry: dict[str, tuple[str, Schema]] = {}
        # Maps type_name → encode_fn for GobEncoder/BinaryMarshaler/TextMarshaler types
        self._gobencoder_registry: dict[str, Callable[[Any], bytes]] = {}
        # Maps type_name → marshaler variant: "gob", "binary", or "text" (default "gob")
        self._marshaler_type_registry: dict[str, str] = {}
        if codecs:
            for type_name, codec in codecs.items():
                self._gobencoder_registry[type_name] = codec.encode
                self._marshaler_type_registry[type_name] = codec.marshaler_type

    def register(self, go_name: str, schema: Schema) -> None:
        """Register a concrete type for interface field encoding.

        When a struct field typed as ``interface{}`` holds a value whose short
        type name matches *schema.name*, the encoder uses *go_name* as the
        string written into the interface field header (e.g. ``"main.Point"``).

        Args:
            go_name: The fully qualified Go type name as passed to
                ``gob.Register`` on the Go side (e.g. ``"main.Point"``).
            schema: A Schema describing the concrete type's fields.  The
                schema's *name* attribute is used as the lookup key when
                matching against a GobStruct's ``gob_type``.
        """
        self._interface_registry[schema.name] = (go_name, schema)

    def register_codec(
        self,
        type_name: str,
        encode_fn: Callable[[Any], bytes],
        marshaler_type: str = "gob",
    ) -> None:
        """Register a custom encoder for a GobEncoder, BinaryMarshaler, or TextMarshaler type.

        When :meth:`encode_gob_encoded` is called with a *type_name* that has a
        registered codec and a non-``GobEncoded`` value, *encode_fn* is invoked
        to convert the Python value to opaque bytes.

        Args:
            type_name: The Go type name (e.g. ``"Time"``).
            encode_fn: A callable ``(value) -> bytes`` that serialises the
                Python value to the opaque byte representation expected by Go.
            marshaler_type: The Go interface the type implements: ``"gob"``
                (GobEncoder, the default), ``"binary"`` (BinaryMarshaler), or
                ``"text"`` (TextMarshaler).  Must match the Go side.
        """
        self._gobencoder_registry[type_name] = encode_fn
        self._marshaler_type_registry[type_name] = marshaler_type

    def encode_gob_encoded(self, value: Any, type_name: str) -> None:
        """Encode *value* as a GobEncoder-type gob message.

        If *value* is a :class:`~pygob.types.GobEncoded` instance its ``.data``
        bytes are used directly.  Otherwise a codec registered via
        :meth:`register_codec` is called to produce the bytes.

        Args:
            value: A ``GobEncoded`` instance, or an arbitrary Python object for
                which a codec has been registered under *type_name*.
            type_name: The Go type name to use for the wire type definition.

        Raises:
            GobEncodeError: if *value* is not a ``GobEncoded`` and no codec
                is registered for *type_name*.
        """
        if isinstance(value, GobEncoded):
            data = value.data
        elif type_name in self._gobencoder_registry:
            data = self._gobencoder_registry[type_name](value)
        else:
            raise GobEncodeError(
                f"no encoder registered for GobEncoder type {type_name!r}; "
                "call register_codec(type_name, encode_fn) first, "
                "or pass a GobEncoded instance"
            )
        type_id = self._emit_gob_encoder_type_definition(type_name)
        payload = b"\x00" + encode_uint(len(data)) + data
        self._emit_value(type_id, payload)

    def encode_interface(self, value: Any) -> None:
        """Encode a concrete interface value to the stream.

        Convenience wrapper around :meth:`encode` for values that are used as
        concrete types inside ``interface{}`` fields.  The concrete type must
        have been registered with :meth:`register`.

        Args:
            value: A ``GobStruct`` or ``@gobstruct`` dataclass instance.
        """
        self.encode(value)

    def _emit_type_definition(self, schema: Schema) -> int:
        """Ensure a type definition for *schema* is emitted; return its type ID.

        Idempotent: calling this multiple times with the same schema emits the
        type definition only once.  Nested struct schemas are emitted first so
        that inner type IDs are always defined before the outer type references
        them.

        Args:
            schema: A Schema describing a gob struct type.

        Returns:
            The type ID assigned to *schema*.
        """
        if schema.name in self._schema_registry:
            return self._schema_registry[schema.name]

        # Recursively emit type defs for nested fields first
        for field_desc in schema.fields.values():
            self._pre_emit_field_type(field_desc)

        # Assign a new type ID
        type_id = self._next_id
        self._next_id += 1
        self._schema_registry[schema.name] = type_id

        # Encode the wireType and write the framed type-definition message
        wire_bytes = self._encode_struct_wire_type(schema, type_id)
        msg = encode_int(-type_id) + wire_bytes
        self._stream.write(encode_uint(len(msg)))
        self._stream.write(msg)
        return type_id

    def _pre_emit_field_type(self, field_desc: object) -> None:
        """Pre-emit any type definitions required by *field_desc*.

        Called during :meth:`_emit_type_definition` so that all types
        referenced by a struct's fields are defined before the struct itself.
        Idempotent — all underlying emit methods cache by type signature.

        Args:
            field_desc: A field type descriptor (int, Schema, SliceOf,
                MapOf, or ArrayOf).
        """
        if isinstance(field_desc, Schema):
            self._emit_type_definition(field_desc)
        elif isinstance(field_desc, SliceOf):
            self._pre_emit_field_type(field_desc.elem_type)
            elem_id = self._field_desc_to_type_id(field_desc.elem_type)
            self._emit_slice_type_definition(elem_id)
        elif isinstance(field_desc, MapOf):
            self._pre_emit_field_type(field_desc.key_type)
            self._pre_emit_field_type(field_desc.val_type)
            key_id = self._field_desc_to_type_id(field_desc.key_type)
            val_id = self._field_desc_to_type_id(field_desc.val_type)
            self._emit_map_type_definition(key_id, val_id)
        elif isinstance(field_desc, ArrayOf):
            self._pre_emit_field_type(field_desc.elem_type)
            elem_id = self._field_desc_to_type_id(field_desc.elem_type)
            self._emit_array_type_definition(elem_id, field_desc.length)
        # int bootstrap IDs need no pre-emission

    def _emit_value(self, type_id: int, payload: bytes) -> None:
        """Write a framed value message.

        Format: ``uint(byteCount) int(type_id) payload``

        Args:
            type_id: The positive gob type ID identifying the value's type.
            payload: The encoded value bytes (not including the type_id header).
        """
        msg = encode_int(type_id) + payload
        self._stream.write(encode_uint(len(msg)))
        self._stream.write(msg)

    def encode(
        self,
        value: object,
        *,
        schema: Schema | None = None,
        elem_type: int | None = None,
        key_type: int | None = None,
        array_length: int | None = None,
    ) -> None:
        """Encode a top-level value and write it to the stream.

        When *schema* is provided, *value* must be a ``dict`` and is encoded as
        a gob struct using that schema.  The type definition is emitted
        automatically on first use (idempotent across calls).

        Without *schema*, the following types are supported:

        * Scalars: ``bool``, ``UInt``, ``int``, ``float``, ``complex``,
          ``str``, ``bytes`` — singleton-wrapped.
        * ``list`` → gob slice (default) or gob array when *array_length* is
          given.  Element type is inferred from the first element, or may be
          supplied via *elem_type* (required for empty lists).
        * ``dict`` → gob map.  Key and element types are inferred from the
          first entry, or may be supplied via *key_type* / *elem_type*
          (both required for empty dicts).
        * ``GobStruct`` or ``@gobstruct`` dataclass — struct encoding.

        Args:
            value: The Python value to encode.
            schema: Optional Schema for struct encoding.
            elem_type: Bootstrap type ID for list/dict element type (e.g.
                ``GOB_INT``).  Required when *value* is an empty list/dict.
            key_type: Bootstrap type ID for dict key type.  Required when
                *value* is an empty dict.
            array_length: When set, encode a ``list`` as a fixed-size gob
                array of this length rather than as a slice.  The list must
                have exactly *array_length* elements.

        Raises:
            GobEncodeError: if *value* is not a supported type, mismatches
                schema, or a collection type cannot be inferred.
        """
        if isinstance(value, GobEncoded) and schema is None:
            self.encode_gob_encoded(value, value.type_name)
            return

        if isinstance(value, GobStruct) and schema is None:
            type_id = self._emit_type_definition(value.gob_schema)
            deferred: list = []
            payload = self._encode_struct_payload(value, value.gob_schema, _deferred=deferred)
            self._emit_value(type_id, payload)
            for defer_type_id, defer_payload in deferred:
                self._emit_value(defer_type_id, defer_payload)
            return

        # @gobstruct dataclass: schema is stored on the class as __gob_schema__
        if dataclasses.is_dataclass(value) and not isinstance(value, type) and schema is None:
            cls_schema = getattr(type(value), "__gob_schema__", None)
            if cls_schema is not None:
                type_id = self._emit_type_definition(cls_schema)
                deferred = []
                payload = self._encode_struct_payload(value, cls_schema, _deferred=deferred)
                self._emit_value(type_id, payload)
                for defer_type_id, defer_payload in deferred:
                    self._emit_value(defer_type_id, defer_payload)
                return

        if schema is not None:
            if not isinstance(value, (dict, GobStruct)):
                raise GobEncodeError(
                    f"struct encoding requires a dict or GobStruct, got {type(value).__name__!r}"
                )
            type_id = self._emit_type_definition(schema)
            deferred = []
            payload = self._encode_struct_payload(value, schema, _deferred=deferred)
            self._emit_value(type_id, payload)
            for defer_type_id, defer_payload in deferred:
                self._emit_value(defer_type_id, defer_payload)
            return

        # bool must be checked before int (bool is a subclass of int).
        # UInt must be checked before int.
        if isinstance(value, bool):
            self._emit_value(BOOL, b"\x00" + encode_bool(value))
        elif isinstance(value, UInt):
            self._emit_value(UINT, b"\x00" + encode_uint(int(value)))
        elif isinstance(value, int):
            self._emit_value(INT, b"\x00" + encode_int(value))
        elif isinstance(value, float):
            self._emit_value(FLOAT, b"\x00" + encode_float(value))
        elif isinstance(value, complex):
            self._emit_value(COMPLEX, b"\x00" + encode_complex(value))
        elif isinstance(value, str):
            self._emit_value(STRING, b"\x00" + encode_string(value))
        elif isinstance(value, bytes):
            self._emit_value(BYTES, b"\x00" + encode_bytes(value))
        elif isinstance(value, list):
            resolved_elem = self._resolve_elem_type(value, elem_type, "list")
            elem_type_id = self._field_desc_to_type_id(resolved_elem)
            if array_length is not None:
                if len(value) != array_length:
                    raise GobEncodeError(
                        f"array_length={array_length} but list has {len(value)} elements"
                    )
                type_id = self._emit_array_type_definition(elem_type_id, array_length)
            else:
                type_id = self._emit_slice_type_definition(elem_type_id)
            payload = b"\x00" + encode_uint(len(value))
            for item in value:
                payload += self._encode_field_value(item, resolved_elem)
            self._emit_value(type_id, payload)
        elif isinstance(value, dict):
            first_key = next(iter(value), None)
            resolved_key = key_type if key_type is not None else (
                self._infer_field_desc(first_key) if first_key is not None else None
            )
            resolved_elem_d = elem_type if elem_type is not None else (
                self._infer_field_desc(value[first_key]) if first_key is not None else None
            )
            if resolved_key is None or resolved_elem_d is None:
                raise GobEncodeError(
                    "cannot encode empty dict without key_type and elem_type; "
                    "pass key_type=GOB_STRING, elem_type=GOB_INT etc."
                )
            key_type_id = self._field_desc_to_type_id(resolved_key)
            elem_type_id_d = self._field_desc_to_type_id(resolved_elem_d)
            type_id = self._emit_map_type_definition(key_type_id, elem_type_id_d)
            payload = b"\x00" + encode_uint(len(value))
            for k, v in value.items():
                payload += self._encode_field_value(k, resolved_key)
                payload += self._encode_field_value(v, resolved_elem_d)
            self._emit_value(type_id, payload)
        else:
            raise GobEncodeError(
                f"unsupported type for encode: {type(value).__name__!r}"
            )

    # -----------------------------------------------------------------------
    # Struct value encoding helpers
    # -----------------------------------------------------------------------

    def _is_zero_value(self, value: Any, field_desc: int | Schema) -> bool:
        """Return True if *value* is the gob zero value for *field_desc*.

        Zero-valued fields are omitted from the encoded struct per the gob
        protocol.  ``None`` (e.g. from a missing dict key) is always zero.

        Args:
            value: The field value to check.
            field_desc: A bootstrap type ID (int), ``GOB_DURATION``, or nested Schema.

        Returns:
            True if the field should be omitted from the encoded output.
        """
        if value is None:
            return True
        if isinstance(field_desc, (Schema, SliceOf, MapOf, ArrayOf)):
            return False
        if field_desc == BOOL:
            return value == False  # noqa: E712 — intentional loose check
        if field_desc in (INT, UINT):
            return value == 0
        if field_desc == FLOAT:
            return value == 0.0
        if field_desc == STRING:
            return value == ""
        if field_desc == BYTES:
            return value == b""
        if field_desc == COMPLEX:
            return value == 0j
        if isinstance(field_desc, SemanticType):
            return value == field_desc.zero
        return False

    def _encode_field_value(self, value: Any, field_desc: int | Schema) -> bytes:
        """Encode a single struct field value according to *field_desc*.

        For nested struct fields the payload is the raw struct body (no
        singleton wrapper).

        Args:
            value: The field value to encode.
            field_desc: A bootstrap type ID (int) or nested Schema.

        Returns:
            The encoded bytes for this field.

        Raises:
            GobEncodeError: for unsupported, unrecognised, or mismatched types.
        """
        if isinstance(field_desc, Schema):
            if not isinstance(value, (dict, GobStruct)) and not (
                dataclasses.is_dataclass(value) and not isinstance(value, type)
            ):
                raise GobEncodeError(
                    f"struct field {field_desc.name!r} requires a dict, GobStruct, or "
                    f"@gobstruct dataclass, got {type(value).__name__!r}"
                )
            return self._encode_struct_payload(value, field_desc)
        if isinstance(field_desc, SliceOf):
            if not isinstance(value, list):
                raise GobEncodeError(
                    f"slice field requires a list, got {type(value).__name__!r}"
                )
            result = encode_uint(len(value))
            for item in value:
                result += self._encode_field_value(item, field_desc.elem_type)
            return result
        if isinstance(field_desc, ArrayOf):
            if not isinstance(value, list):
                raise GobEncodeError(
                    f"array field requires a list, got {type(value).__name__!r}"
                )
            if len(value) != field_desc.length:
                raise GobEncodeError(
                    f"array field requires exactly {field_desc.length} elements, "
                    f"got {len(value)}"
                )
            result = encode_uint(len(value))
            for item in value:
                result += self._encode_field_value(item, field_desc.elem_type)
            return result
        if isinstance(field_desc, MapOf):
            if not isinstance(value, dict):
                raise GobEncodeError(
                    f"map field requires a dict, got {type(value).__name__!r}"
                )
            result = encode_uint(len(value))
            for k, v in value.items():
                result += self._encode_field_value(k, field_desc.key_type)
                result += self._encode_field_value(v, field_desc.val_type)
            return result
        if field_desc == BOOL:
            if not isinstance(value, (bool, int)):
                raise GobEncodeError(
                    f"bool field requires a bool or int value, got {type(value).__name__!r}"
                )
            return encode_bool(bool(value))
        if field_desc == INT:
            if not isinstance(value, int):
                raise GobEncodeError(
                    f"int field requires an int value, got {type(value).__name__!r}"
                )
            return encode_int(int(value))
        if field_desc == UINT:
            if not isinstance(value, int):
                raise GobEncodeError(
                    f"uint field requires an int value, got {type(value).__name__!r}"
                )
            if value < 0:
                raise GobEncodeError(
                    f"uint field requires a non-negative value, got {value!r}"
                )
            return encode_uint(int(value))
        if field_desc == FLOAT:
            if not isinstance(value, (int, float)):
                raise GobEncodeError(
                    f"float field requires a numeric value, got {type(value).__name__!r}"
                )
            return encode_float(float(value))
        if field_desc == STRING:
            if not isinstance(value, str):
                raise GobEncodeError(
                    f"string field requires a str value, got {type(value).__name__!r}"
                )
            return encode_string(value)
        if field_desc == BYTES:
            if not isinstance(value, (bytes, bytearray)):
                raise GobEncodeError(
                    f"bytes field requires a bytes value, got {type(value).__name__!r}"
                )
            return encode_bytes(bytes(value))
        if field_desc == COMPLEX:
            if not isinstance(value, (int, float, complex)):
                raise GobEncodeError(
                    f"complex field requires a numeric value, got {type(value).__name__!r}"
                )
            return encode_complex(complex(value))
        if isinstance(field_desc, SemanticType):
            try:
                wire_value = field_desc.encode(value)
            except Exception as exc:
                raise GobEncodeError(
                    f"SemanticType encode failed for value {value!r}: {exc}"
                ) from exc
            return self._encode_field_value(wire_value, field_desc.wire_type)
        raise GobEncodeError(f"unsupported field type descriptor: {field_desc!r}")

    def _encode_struct_payload(
        self, value: Any, schema: Schema, *, _deferred: list | None = None
    ) -> bytes:
        """Encode a struct value as a delta-encoded field sequence.

        Fields with zero values are omitted.  The sequence is terminated with
        a single ``0x00`` byte per the gob struct encoding protocol.

        When a field has type ``INTERFACE``, the concrete value is encoded
        inline (type name + wireType bytes) and a deferred concrete-value
        message is appended to *_deferred* for the caller to emit afterwards.

        Args:
            value: A dict, ``GobStruct``, or ``@gobstruct`` dataclass.
            schema: The Schema describing the struct's fields and types.
            _deferred: Optional list that receives ``(type_id, payload)``
                tuples for interface concrete-value messages that must be
                emitted as separate framed messages after the struct.

        Returns:
            The encoded struct bytes including the terminal ``0x00``.
        """
        result = b""
        prev_field = -1
        for field_index, (field_name, field_desc) in enumerate(schema.fields.items()):
            field_value = value.get(field_name) if isinstance(value, dict) else getattr(value, field_name, None)
            if self._is_zero_value(field_value, field_desc):
                continue
            delta = field_index - prev_field
            result += encode_uint(delta)
            if field_desc == INTERFACE:
                if _deferred is None:
                    raise GobEncodeError(
                        "encoding a struct with interface fields requires "
                        "_deferred list; call encode() instead of _encode_struct_payload() directly"
                    )
                result += self._encode_interface_field(field_value, _deferred)
            else:
                result += self._encode_field_value(field_value, field_desc)
            prev_field = field_index
        result += encode_uint(0)  # struct terminator
        return result

    def _encode_interface_field(self, value: Any, deferred: list) -> bytes:
        """Encode a non-nil interface field value inline.

        Writes the concrete Go type name string, an inline wireType definition
        for the concrete type, and a terminator into the enclosing struct
        payload.  Appends ``(type_id, concrete_payload)`` to *deferred* so
        the caller can emit the concrete-value message as a separate framed
        message after the struct.

        Args:
            value: The concrete value — a ``GobStruct`` or ``@gobstruct``
                dataclass.  Must have been registered with :meth:`register`.
            deferred: List that receives ``(type_id, payload)`` tuples for
                deferred concrete-value messages.

        Returns:
            The inline interface field bytes to embed in the struct payload.

        Raises:
            GobEncodeError: if the value's type is not registered or
                unsupported.
        """
        if isinstance(value, GobStruct):
            short_name = value.gob_type
            schema = value.gob_schema
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            cls_schema = getattr(type(value), "__gob_schema__", None)
            if cls_schema is None:
                raise GobEncodeError(
                    "@gobstruct dataclass has no __gob_schema__; use the @gobstruct decorator"
                )
            short_name = cls_schema.name
            schema = cls_schema
        else:
            raise GobEncodeError(
                f"interface field value must be a GobStruct or @gobstruct dataclass, "
                f"got {type(value).__name__!r}"
            )

        if short_name not in self._interface_registry:
            # Fall back to the module-level @gobstruct auto-registry.
            # The go_name defaults to the schema name (short name).  If the Go
            # side registered with a qualified name (e.g. "main.Point"), call
            # encoder.register("main.Point", schema) explicitly.
            from pygob.types import _GOBSTRUCT_REGISTRY
            if short_name in _GOBSTRUCT_REGISTRY:
                go_name = short_name
            else:
                raise GobEncodeError(
                    f"type {short_name!r} is not registered for interface encoding; "
                    "call encoder.register(go_name, schema) first, "
                    "or decorate the class with @gobstruct"
                )
        else:
            go_name, _ = self._interface_registry[short_name]

        # Assign type_id for the concrete type WITHOUT writing a type-def message.
        # Interface concrete types are defined inline, not as separate messages.
        if schema.name not in self._schema_registry:
            self._schema_registry[schema.name] = self._next_id
            self._next_id += 1
        concrete_type_id = self._schema_registry[schema.name]

        # Build inline wireType bytes for the concrete struct type.
        wire_bytes = self._encode_struct_wire_type(schema, concrete_type_id)

        # Interface field inline encoding:
        #   encode_string(go_name) + encode_int(-concrete_type_id) + wire_bytes
        # The enclosing struct's terminator 0x00 also terminates the inline type
        # defs loop in Go's decoder, so no separate terminator is emitted here.
        iface_bytes = (
            encode_string(go_name)
            + encode_int(-concrete_type_id)
            + wire_bytes
        )

        # Build the byte-count-wrapped struct payload for the concrete value.
        # Go's gob decoder expects: uint(N) + struct_bytes(N) + trailing 0x00.
        inner_deferred: list = []
        struct_bytes = self._encode_struct_payload(value, schema, _deferred=inner_deferred)
        concrete_payload = encode_uint(len(struct_bytes)) + struct_bytes + b"\x00"

        deferred.append((concrete_type_id, concrete_payload))
        deferred.extend(inner_deferred)

        return iface_bytes

    # -----------------------------------------------------------------------
    # Collection type helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _infer_type_id(value: Any) -> int:
        """Infer the bootstrap gob type ID for a scalar Python value.

        Args:
            value: A scalar Python value.

        Returns:
            A bootstrap type ID constant (BOOL, INT, UINT, etc.).

        Raises:
            GobEncodeError: if no mapping exists for the value's type.
        """
        if isinstance(value, bool):
            return BOOL
        if isinstance(value, UInt):
            return UINT
        if isinstance(value, int):
            return INT
        if isinstance(value, float):
            return FLOAT
        if isinstance(value, complex):
            return COMPLEX
        if isinstance(value, str):
            return STRING
        if isinstance(value, bytes):
            return BYTES
        raise GobEncodeError(
            f"cannot infer gob type for {type(value).__name__!r}; "
            "pass elem_type= or key_type= explicitly"
        )

    def _infer_field_desc(self, value: Any) -> int | Schema:
        """Infer a field descriptor (bootstrap type ID or Schema) for *value*.

        Extends :meth:`_infer_type_id` to also handle ``GobStruct`` and
        ``@gobstruct``-decorated dataclass instances.

        Args:
            value: A Python value.

        Returns:
            A bootstrap type ID (int) for scalar types, or a ``Schema`` for
            struct types.

        Raises:
            GobEncodeError: if no mapping exists for the value's type.
        """
        if isinstance(value, GobStruct):
            return value.gob_schema
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            cls_schema = getattr(type(value), "__gob_schema__", None)
            if cls_schema is not None:
                return cls_schema
        return self._infer_type_id(value)

    def _field_desc_to_type_id(self, field_desc: int | Schema | SliceOf | MapOf | ArrayOf) -> int:
        """Return the gob type ID for *field_desc*, emitting a type definition if needed.

        For ``Schema`` descriptors the type definition is emitted on first call
        (idempotent thereafter).  For collection descriptors the appropriate
        collection type definition is emitted.  For integer bootstrap IDs the
        value is returned directly.

        Args:
            field_desc: A bootstrap type ID, ``Schema``, ``SliceOf``,
                ``MapOf``, or ``ArrayOf`` descriptor.

        Returns:
            The resolved gob type ID.
        """
        if isinstance(field_desc, Schema):
            return self._emit_type_definition(field_desc)
        if isinstance(field_desc, SliceOf):
            elem_id = self._field_desc_to_type_id(field_desc.elem_type)
            return self._emit_slice_type_definition(elem_id)
        if isinstance(field_desc, MapOf):
            key_id = self._field_desc_to_type_id(field_desc.key_type)
            val_id = self._field_desc_to_type_id(field_desc.val_type)
            return self._emit_map_type_definition(key_id, val_id)
        if isinstance(field_desc, ArrayOf):
            elem_id = self._field_desc_to_type_id(field_desc.elem_type)
            return self._emit_array_type_definition(elem_id, field_desc.length)
        if isinstance(field_desc, SemanticType):
            return field_desc.wire_type
        return field_desc  # int bootstrap type ID

    def _resolve_elem_type(
        self, value: list, elem_type: int | Schema | None, label: str
    ) -> int | Schema:
        """Return the element field descriptor for *value*, inferring from the first element if needed.

        Args:
            value: The collection whose element type to resolve.
            elem_type: Caller-supplied override (may be None).
            label: Human-readable collection kind for error messages.

        Returns:
            A bootstrap type ID (int) or a ``Schema`` for struct element types.

        Raises:
            GobEncodeError: if *value* is empty and *elem_type* is None.
        """
        if elem_type is not None:
            return elem_type
        if not value:
            raise GobEncodeError(
                f"cannot encode empty {label} without elem_type; "
                "pass elem_type=GOB_INT etc."
            )
        return self._infer_field_desc(value[0])

    def _emit_slice_type_definition(self, elem_type_id: int) -> int:
        """Ensure a SliceWireType definition is emitted and return its type ID.

        Args:
            elem_type_id: Bootstrap type ID of the slice's element type.

        Returns:
            The type ID assigned to this slice type.
        """
        key = ("slice", elem_type_id)
        if key in self._collection_registry:
            return self._collection_registry[key]
        type_id = self._next_id
        self._next_id += 1
        self._collection_registry[key] = type_id
        wire_bytes = self._encode_slice_wire_type(elem_type_id, type_id)
        msg = encode_int(-type_id) + wire_bytes
        self._stream.write(encode_uint(len(msg)))
        self._stream.write(msg)
        return type_id

    def _emit_array_type_definition(self, elem_type_id: int, length: int) -> int:
        """Ensure an ArrayWireType definition is emitted and return its type ID.

        Args:
            elem_type_id: Bootstrap type ID of the array's element type.
            length: The fixed number of elements in the array.

        Returns:
            The type ID assigned to this array type.
        """
        key = ("array", elem_type_id, length)
        if key in self._collection_registry:
            return self._collection_registry[key]
        type_id = self._next_id
        self._next_id += 1
        self._collection_registry[key] = type_id
        wire_bytes = self._encode_array_wire_type(elem_type_id, length, type_id)
        msg = encode_int(-type_id) + wire_bytes
        self._stream.write(encode_uint(len(msg)))
        self._stream.write(msg)
        return type_id

    def _emit_map_type_definition(self, key_type_id: int, elem_type_id: int) -> int:
        """Ensure a MapWireType definition is emitted and return its type ID.

        Args:
            key_type_id: Bootstrap type ID of the map's key type.
            elem_type_id: Bootstrap type ID of the map's element type.

        Returns:
            The type ID assigned to this map type.
        """
        key = ("map", key_type_id, elem_type_id)
        if key in self._collection_registry:
            return self._collection_registry[key]
        type_id = self._next_id
        self._next_id += 1
        self._collection_registry[key] = type_id
        wire_bytes = self._encode_map_wire_type(key_type_id, elem_type_id, type_id)
        msg = encode_int(-type_id) + wire_bytes
        self._stream.write(encode_uint(len(msg)))
        self._stream.write(msg)
        return type_id

    def _emit_gob_encoder_type_definition(self, type_name: str) -> int:
        """Ensure a marshaler WireType definition is emitted for *type_name*; return its type ID.

        The wire field variant (GobEncoderT/BinaryMarshalerT/TextMarshalerT) is
        determined by the *marshaler_type* registered via ``register_codec`` or
        the ``codecs=`` constructor kwarg (default: ``"gob"`` = GobEncoderT).

        Args:
            type_name: The Go type name for the marshaler type.

        Returns:
            The type ID assigned to this marshaler type.
        """
        if type_name in self._schema_registry:
            return self._schema_registry[type_name]

        type_id = self._next_id
        self._next_id += 1
        self._schema_registry[type_name] = type_id

        marshaler_type = self._marshaler_type_registry.get(type_name, "gob")
        wire_bytes = self._encode_gob_encoder_wire_type(type_name, type_id, marshaler_type)
        msg = encode_int(-type_id) + wire_bytes
        self._stream.write(encode_uint(len(msg)))
        self._stream.write(msg)
        return type_id

    # -----------------------------------------------------------------------
    # Wire type encoding helpers
    # -----------------------------------------------------------------------

    def _encode_struct_wire_type(self, schema: Schema, type_id: int) -> bytes:
        """Encode *schema* as a WireType struct (StructT variant at field position 2).

        The WireType outer struct encodes field 2 (StructT) using a delta of 3
        (advancing from the conceptual starting position of -1 to field index 2).

        Args:
            schema: The Schema to encode.
            type_id: The type ID that will be embedded in the CommonType.id field.

        Returns:
            The encoded wireType bytes (outer WireType struct, including its
            terminator, but *not* the framing byte-count or the type-id prefix).
        """
        struct_bytes = self._encode_struct_wire_type_fields(schema, type_id)
        # WireType outer: delta=3 (field 2 = StructT), inline StructWireType, terminator
        return encode_uint(3) + struct_bytes + encode_uint(0)

    def _encode_struct_wire_type_fields(self, schema: Schema, type_id: int) -> bytes:
        """Encode the fields of a StructWireType struct inline.

        Field 0 = CommonType (name + id), field 1 = Fields (count + FieldWireTypes).

        Args:
            schema: The Schema to encode.
            type_id: The type ID for the CommonType.id field.

        Returns:
            The encoded StructWireType bytes including its own struct terminator.
        """
        common_bytes = self._encode_common_type(schema.name, type_id)
        fields_payload = encode_uint(len(schema.fields))
        for field_name, field_desc in schema.fields.items():
            field_type_id = self._resolve_field_type_id(field_desc)
            fields_payload += self._encode_field_wire_type(field_name, field_type_id)

        result = encode_uint(1) + common_bytes     # delta=1 → field 0 (CommonType)
        result += encode_uint(1) + fields_payload  # delta=1 → field 1 (Fields)
        result += encode_uint(0)                   # struct terminator
        return result

    def _encode_common_type(self, name: str, type_id: int) -> bytes:
        """Encode a CommonType struct (Name string, Id typeId) inline.

        An empty *name* is the gob zero value for string and is omitted per
        the struct-encoding protocol (used by slice, array, and map types).

        Args:
            name: The Go type name (empty string for anonymous collection types).
            type_id: The assigned gob type ID.

        Returns:
            The encoded CommonType bytes including its struct terminator.
        """
        result = b""
        if name:
            result += encode_uint(1) + encode_string(name)   # delta=1 → field 0 (Name)
            result += encode_uint(1) + encode_int(type_id)   # delta=1 → field 1 (Id)
        else:
            # Name is empty (zero value) — skip directly to field 1 (Id)
            result += encode_uint(2) + encode_int(type_id)   # delta=2 → field 1 (Id)
        result += encode_uint(0)                              # struct terminator
        return result

    def _encode_slice_wire_type(self, elem_type_id: int, type_id: int) -> bytes:
        """Encode a SliceWireType as a WireType struct (field 1 = SliceT).

        Args:
            elem_type_id: Bootstrap type ID for the element type.
            type_id: The type ID embedded in the CommonType.

        Returns:
            Encoded WireType bytes (outer struct, including terminators).
        """
        common_bytes = self._encode_common_type("", type_id)
        slice_bytes = (
            encode_uint(1) + common_bytes                       # delta=1 → field 0 (CommonType)
            + encode_uint(1) + encode_int(elem_type_id)         # delta=1 → field 1 (Elem)
            + encode_uint(0)                                    # SliceWireType terminator
        )
        # WireType field 1 = SliceT: delta from starting position -1 = 2
        return encode_uint(2) + slice_bytes + encode_uint(0)

    def _encode_array_wire_type(self, elem_type_id: int, length: int, type_id: int) -> bytes:
        """Encode an ArrayWireType as a WireType struct (field 0 = ArrayT).

        Args:
            elem_type_id: Bootstrap type ID for the element type.
            length: The fixed number of elements in the array.
            type_id: The type ID embedded in the CommonType.

        Returns:
            Encoded WireType bytes (outer struct, including terminators).
        """
        common_bytes = self._encode_common_type("", type_id)
        array_bytes = (
            encode_uint(1) + common_bytes                       # delta=1 → field 0 (CommonType)
            + encode_uint(1) + encode_int(elem_type_id)         # delta=1 → field 1 (Elem)
            + encode_uint(1) + encode_int(length)               # delta=1 → field 2 (Len)
            + encode_uint(0)                                    # ArrayWireType terminator
        )
        # WireType field 0 = ArrayT: delta from starting position -1 = 1
        return encode_uint(1) + array_bytes + encode_uint(0)

    def _encode_map_wire_type(
        self, key_type_id: int, elem_type_id: int, type_id: int
    ) -> bytes:
        """Encode a MapWireType as a WireType struct (field 3 = MapT).

        Args:
            key_type_id: Bootstrap type ID for the key type.
            elem_type_id: Bootstrap type ID for the element type.
            type_id: The type ID embedded in the CommonType.

        Returns:
            Encoded WireType bytes (outer struct, including terminators).
        """
        common_bytes = self._encode_common_type("", type_id)
        map_bytes = (
            encode_uint(1) + common_bytes                       # delta=1 → field 0 (CommonType)
            + encode_uint(1) + encode_int(key_type_id)          # delta=1 → field 1 (Key)
            + encode_uint(1) + encode_int(elem_type_id)         # delta=1 → field 2 (Elem)
            + encode_uint(0)                                    # MapWireType terminator
        )
        # WireType field 3 = MapT: delta from starting position -1 = 4
        return encode_uint(4) + map_bytes + encode_uint(0)

    def _encode_gob_encoder_wire_type(
        self, type_name: str, type_id: int, marshaler_type: str = "gob"
    ) -> bytes:
        """Encode a marshaler WireType struct for the given variant.

        The outer WireType struct field positions:
          Field 4 = GobEncoderT      (delta from -1 = 5) for GobEncoder
          Field 5 = BinaryMarshalerT (delta from -1 = 6) for BinaryMarshaler
          Field 6 = TextMarshalerT   (delta from -1 = 7) for TextMarshaler

        Args:
            type_name: The Go type name embedded in the CommonType.
            type_id: The type ID embedded in the CommonType.
            marshaler_type: ``"gob"``, ``"binary"``, or ``"text"``.

        Returns:
            Encoded WireType bytes (outer struct, including terminators).
        """
        common_bytes = self._encode_common_type(type_name, type_id)
        inner_bytes = (
            encode_uint(1) + common_bytes   # delta=1 → field 0 (CommonType)
            + encode_uint(0)                # inner WireType terminator
        )
        # Map marshaler_type to the outer WireType delta (field index + 1, since we start from -1)
        _DELTA = {"gob": 5, "binary": 6, "text": 7}
        delta = _DELTA.get(marshaler_type, 5)
        return encode_uint(delta) + inner_bytes + encode_uint(0)

    def _encode_field_wire_type(self, name: str, type_id: int) -> bytes:
        """Encode a FieldWireType struct (Name string, Id typeId) inline.

        Args:
            name: The field name.
            type_id: The gob type ID of this field's type.

        Returns:
            The encoded FieldWireType bytes including its struct terminator.
        """
        result = encode_uint(1) + encode_string(name)   # delta=1 → field 0 (Name)
        result += encode_uint(1) + encode_int(type_id)  # delta=1 → field 1 (Id)
        result += encode_uint(0)                         # struct terminator
        return result

    def _resolve_field_type_id(self, field_desc: int | Schema | SliceOf | MapOf | ArrayOf) -> int:
        """Resolve a field descriptor to a concrete gob type ID.

        All necessary type definitions must already have been emitted via
        :meth:`_pre_emit_field_type` before this is called (e.g. from within
        :meth:`_emit_type_definition`).

        Args:
            field_desc: A bootstrap type ID, nested Schema, or collection
                descriptor (SliceOf, MapOf, ArrayOf).

        Returns:
            The gob type ID for the field's type.

        Raises:
            GobEncodeError: if a type has no ID assigned yet.
        """
        if isinstance(field_desc, Schema):
            name = field_desc.name
            if name not in self._schema_registry:
                raise GobEncodeError(
                    f"nested schema {name!r} has no type ID assigned yet; "
                    "ensure _emit_type_definition is called for nested schemas first"
                )
            return self._schema_registry[name]
        if isinstance(field_desc, SliceOf):
            elem_id = self._resolve_field_type_id(field_desc.elem_type)
            key = ("slice", elem_id)
            if key not in self._collection_registry:
                raise GobEncodeError(
                    f"slice type for elem_id={elem_id} has no type ID assigned yet; "
                    "ensure _pre_emit_field_type is called first"
                )
            return self._collection_registry[key]
        if isinstance(field_desc, MapOf):
            key_id = self._resolve_field_type_id(field_desc.key_type)
            val_id = self._resolve_field_type_id(field_desc.val_type)
            key = ("map", key_id, val_id)
            if key not in self._collection_registry:
                raise GobEncodeError(
                    f"map type for key_id={key_id}, val_id={val_id} has no type ID yet; "
                    "ensure _pre_emit_field_type is called first"
                )
            return self._collection_registry[key]
        if isinstance(field_desc, ArrayOf):
            elem_id = self._resolve_field_type_id(field_desc.elem_type)
            key = ("array", elem_id, field_desc.length)
            if key not in self._collection_registry:
                raise GobEncodeError(
                    f"array type for elem_id={elem_id}, len={field_desc.length} has no type ID yet; "
                    "ensure _pre_emit_field_type is called first"
                )
            return self._collection_registry[key]
        if isinstance(field_desc, SemanticType):
            return field_desc.wire_type
        return field_desc  # int bootstrap type ID
