"""Public type system: GobStruct, UInt, Schema, GobEncoded, SemanticType, and the @gobstruct decorator."""

from __future__ import annotations

import dataclasses
from typing import Any, Callable, get_args, get_origin

from datetime import timedelta as _timedelta

from pygob.wire import BOOL, INT, UINT, FLOAT, BYTES, STRING, COMPLEX, INTERFACE

# Re-export as GOB_* constants for public API convenience
GOB_BOOL = BOOL
GOB_INT = INT
GOB_UINT = UINT
GOB_FLOAT = FLOAT
GOB_BYTES = BYTES
GOB_STRING = STRING
GOB_COMPLEX = COMPLEX
GOB_INTERFACE = INTERFACE


class UInt(int):
    """Marker for unsigned int encoding. Subclasses int so it works everywhere."""
    pass


# ---------------------------------------------------------------------------
# SemanticType — Python-side conversion over a primitive wire type
# ---------------------------------------------------------------------------


class SemanticType:
    """Schema field descriptor for Go named primitive types.

    Use this when a Go type is defined as a named alias over a primitive
    (e.g. ``type Duration int64``, ``type Status string``) and you want the
    Python side to use a richer type with automatic conversion.

    The *wire_type* must be a bootstrap type ID (``GOB_INT``, ``GOB_STRING``,
    ``GOB_FLOAT``, etc.) — the primitive that gob actually encodes on the wire.
    The *encode* and *decode* callables convert between the Python type and the
    wire-compatible primitive.  *zero* is the Python zero value for omit-zero
    detection.  *python_type*, if provided, is used by the ``@gobstruct``
    decorator to infer this descriptor from a type annotation.

    Example — a Go ``type Celsius float64`` field kept as a plain float::

        GOB_CELSIUS = SemanticType(
            wire_type=GOB_FLOAT,
            encode=float,
            decode=float,
            zero=0.0,
            python_type=float,  # omit if not needed in @gobstruct
        )

    Example — a Go ``type Status string`` mapped to a Python enum::

        class Status(enum.Enum):
            active = "active"
            inactive = "inactive"

        GOB_STATUS = SemanticType(
            wire_type=GOB_STRING,
            python_type=Status,
            encode=lambda s: s.value,
            decode=Status,
            zero=Status.active,
        )

        MySchema = Schema("User", Name=GOB_STRING, Status=GOB_STATUS)

    To use a custom ``SemanticType`` with ``@gobstruct`` annotations, register
    it with :func:`register_semantic_type`.
    """

    def __init__(
        self,
        *,
        wire_type: int,
        encode: Callable[[Any], Any],
        decode: Callable[[Any], Any],
        zero: Any,
        python_type: type | None = None,
    ) -> None:
        self.wire_type = wire_type
        self.encode = encode
        self.decode = decode
        self.zero = zero
        self.python_type = python_type

    def __repr__(self) -> str:
        return (
            f"SemanticType(wire_type={self.wire_type!r}, python_type={self.python_type!r})"
        )

    def __eq__(self, other: object) -> bool:
        return self is other  # identity comparison — each SemanticType is a singleton

    def __hash__(self) -> int:
        return id(self)


def register_semantic_type(python_type: type, semantic: SemanticType) -> None:
    """Register a :class:`SemanticType` for use in ``@gobstruct`` annotations.

    After registration, ``@gobstruct`` will automatically map fields annotated
    with *python_type* to *semantic* when building the schema.

    Args:
        python_type: The Python annotation type to map (e.g. a custom class).
        semantic: The :class:`SemanticType` descriptor to use for that annotation.

    Example::

        register_semantic_type(Status, GOB_STATUS)

        @gobstruct("User")
        @dataclass
        class User:
            Name: str
            Status: Status   # resolved to GOB_STATUS automatically
    """
    _PYTHON_TO_GOB[python_type] = semantic


# ---------------------------------------------------------------------------
# Collection type descriptors — used in Schema field definitions
# ---------------------------------------------------------------------------


class SliceOf:
    """Field type descriptor for a Go slice type.

    Use as a Schema field type to describe a ``[]T`` Go field::

        Schema("Foo", Items=SliceOf(GOB_INT), Names=SliceOf(GOB_STRING))

    *elem_type* may be a bootstrap type ID (``GOB_INT`` etc.), a ``Schema``
    for struct-typed elements, or another collection descriptor for nested
    collections.
    """

    def __init__(self, elem_type: int | Schema | SliceOf | MapOf | ArrayOf) -> None:
        self.elem_type = elem_type

    def __repr__(self) -> str:
        return f"SliceOf({self.elem_type!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SliceOf):
            return NotImplemented
        return self.elem_type == other.elem_type

    def __hash__(self) -> int:
        return hash(("SliceOf", _hashable(self.elem_type)))


class MapOf:
    """Field type descriptor for a Go map type.

    Use as a Schema field type to describe a ``map[K]V`` Go field::

        Schema("Foo", Counts=MapOf(GOB_STRING, GOB_INT))

    *key_type* must be a bootstrap type ID.  *val_type* may be a bootstrap
    type ID, a ``Schema``, or another collection descriptor.
    """

    def __init__(
        self,
        key_type: int | Schema | SliceOf | MapOf | ArrayOf,
        val_type: int | Schema | SliceOf | MapOf | ArrayOf,
    ) -> None:
        self.key_type = key_type
        self.val_type = val_type

    def __repr__(self) -> str:
        return f"MapOf({self.key_type!r}, {self.val_type!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MapOf):
            return NotImplemented
        return self.key_type == other.key_type and self.val_type == other.val_type

    def __hash__(self) -> int:
        return hash(("MapOf", _hashable(self.key_type), _hashable(self.val_type)))


class ArrayOf:
    """Field type descriptor for a Go array type.

    Use as a Schema field type to describe a ``[N]T`` Go field::

        Schema("Foo", Coords=ArrayOf(GOB_FLOAT, 3))

    *elem_type* may be a bootstrap type ID, a ``Schema``, or another
    collection descriptor.  *length* is the fixed number of elements.
    """

    def __init__(
        self,
        elem_type: int | Schema | SliceOf | MapOf | ArrayOf,
        length: int,
    ) -> None:
        self.elem_type = elem_type
        self.length = length

    def __repr__(self) -> str:
        return f"ArrayOf({self.elem_type!r}, {self.length})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ArrayOf):
            return NotImplemented
        return self.elem_type == other.elem_type and self.length == other.length

    def __hash__(self) -> int:
        return hash(("ArrayOf", _hashable(self.elem_type), self.length))


def _hashable(desc: Any) -> Any:
    """Return a hashable representation of a field type descriptor."""
    if isinstance(desc, (int, str)):
        return desc
    if isinstance(desc, Schema):
        return ("Schema", desc.name)
    if isinstance(desc, SliceOf):
        return ("SliceOf", _hashable(desc.elem_type))
    if isinstance(desc, MapOf):
        return ("MapOf", _hashable(desc.key_type), _hashable(desc.val_type))
    if isinstance(desc, ArrayOf):
        return ("ArrayOf", _hashable(desc.elem_type), desc.length)
    return repr(desc)


class Schema:
    """Describes a gob struct type: its Go name and an ordered mapping of field names to type descriptors.

    Field type descriptors are bootstrap type IDs (GOB_INT, GOB_STRING, etc.),
    nested Schema instances, collection descriptors (SliceOf, MapOf, ArrayOf),
    or SemanticType instances for named primitive types (GOB_DURATION, etc.).
    """

    def __init__(self, name: str, **fields: int | Schema | SliceOf | MapOf | ArrayOf | SemanticType) -> None:
        self.name = name
        # Preserve insertion order (Python 3.7+ dicts are ordered)
        self.fields: dict[str, int | Schema | SliceOf | MapOf | ArrayOf | SemanticType] = dict(fields)

    def __repr__(self) -> str:
        field_parts = ", ".join(f"{k}={v!r}" for k, v in self.fields.items())
        return f"Schema({self.name!r}, {field_parts})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Schema):
            return NotImplemented
        return self.name == other.name and self.fields == other.fields


class GobStruct:
    """A decoded gob struct. Acts like a dict with attribute access.

    Carries its Go type name and full field schema for re-encoding.
    """

    def __init__(self, gob_type: str, gob_schema: Schema, **fields: Any) -> None:
        object.__setattr__(self, "gob_type", gob_type)
        object.__setattr__(self, "gob_schema", gob_schema)
        object.__setattr__(self, "_fields", dict(fields))

    # -- Mapping interface --------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return self._fields[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._fields[key] = value

    def __iter__(self):
        return iter(self._fields)

    def __len__(self) -> int:
        return len(self._fields)

    def keys(self):
        return self._fields.keys()

    def values(self):
        return self._fields.values()

    def items(self):
        return self._fields.items()

    def __contains__(self, key: object) -> bool:
        return key in self._fields

    # -- Attribute access --------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        try:
            return self._fields[name]
        except KeyError:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("gob_type", "gob_schema", "_fields"):
            object.__setattr__(self, name, value)
        else:
            self._fields[name] = value

    # -- Equality and repr -------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GobStruct):
            return self.gob_type == other.gob_type and self._fields == other._fields
        if isinstance(other, dict):
            return self._fields == other
        return NotImplemented

    def __repr__(self) -> str:
        field_str = ", ".join(f"{k}={v!r}" for k, v in self._fields.items())
        return f"GobStruct({self.gob_type!r}, {field_str})"

    # dict() works via __iter__ + __getitem__, but also expose get() for convenience
    def get(self, key: str, default: Any = None) -> Any:
        return self._fields.get(key, default)


class GobEncoded:
    """Holds opaque bytes for a type implementing GobEncoder, BinaryMarshaler, or TextMarshaler."""

    def __init__(self, type_name: str, data: bytes) -> None:
        self.type_name = type_name
        self.data = data

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GobEncoded):
            return NotImplemented
        return self.type_name == other.type_name and self.data == other.data

    def __repr__(self) -> str:
        return f"GobEncoded({self.type_name!r}, {self.data!r})"


# ---------------------------------------------------------------------------
# @gobstruct decorator
# ---------------------------------------------------------------------------

# Built-in SemanticType instances
def _make_duration() -> SemanticType:
    from pygob.codecs import duration_to_timedelta, timedelta_to_duration
    return SemanticType(
        wire_type=GOB_INT,
        python_type=_timedelta,
        encode=timedelta_to_duration,
        decode=duration_to_timedelta,
        zero=_timedelta(0),
    )

GOB_DURATION: SemanticType = _make_duration()
del _make_duration

# Maps Python annotation types to gob type IDs or SemanticType instances
_PYTHON_TO_GOB: dict[type, int | SemanticType] = {
    bool: GOB_BOOL,
    int: GOB_INT,
    UInt: GOB_UINT,
    float: GOB_FLOAT,
    bytes: GOB_BYTES,
    str: GOB_STRING,
    complex: GOB_COMPLEX,
    _timedelta: GOB_DURATION,
}

# Attribute name used to stash the Schema on decorated classes
_SCHEMA_ATTR = "__gob_schema__"

# Module-level registry: Go type name → Schema, populated by @gobstruct.
# The Encoder falls back to this when encoding interface fields without
# an explicit encoder.register() call.
_GOBSTRUCT_REGISTRY: dict[str, "Schema"] = {}


def gobstruct(name: str):
    """Decorator that attaches a gob Schema to a dataclass.

    Usage::

        @gobstruct("Point")
        @dataclass
        class Point:
            X: int
            Y: int

    The decorator inspects the dataclass field annotations to build a Schema.
    Supported annotation types: bool, int, UInt, float, bytes, str, complex,
    datetime.timedelta (→ GOB_DURATION), any class decorated with @gobstruct
    (nested struct), and any type registered via :func:`register_semantic_type`.
    """

    def decorator(cls):
        if not dataclasses.is_dataclass(cls):
            raise TypeError(f"@gobstruct requires a dataclass, got {cls!r}")

        field_types: dict[str, int | Schema | SliceOf | MapOf | ArrayOf | SemanticType] = {}
        for f in dataclasses.fields(cls):
            annotation = f.type
            # If annotation is a string (PEP 563 / from __future__ annotations), resolve it
            if isinstance(annotation, str):
                import sys
                frame = sys._getframe(1)
                ns = {**frame.f_globals, **frame.f_locals}
                annotation = eval(annotation, ns)  # noqa: S307

            gob_type = _resolve_annotation(annotation)
            field_types[f.name] = gob_type

        schema = Schema(name, **field_types)
        cls.__gob_schema__ = schema
        # Auto-register in the module-level registry so that the Encoder
        # can find this type for interface fields without a manual register() call.
        _GOBSTRUCT_REGISTRY[name] = schema
        return cls

    return decorator


def _resolve_annotation(annotation: Any) -> int | Schema | SliceOf | MapOf | ArrayOf | SemanticType:
    """Resolve a Python type annotation to a gob type descriptor."""
    if annotation in _PYTHON_TO_GOB:
        return _PYTHON_TO_GOB[annotation]
    # Nested @gobstruct class
    if hasattr(annotation, _SCHEMA_ATTR):
        return annotation.__gob_schema__

    # Generic aliases: list[T] → SliceOf(T), dict[K, V] → MapOf(K, V)
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is list:
        if len(args) != 1:
            raise TypeError(
                f"list annotation requires exactly one type argument, got {annotation!r}"
            )
        return SliceOf(_resolve_annotation(args[0]))

    if origin is dict:
        if len(args) != 2:
            raise TypeError(
                f"dict annotation requires exactly two type arguments, got {annotation!r}"
            )
        return MapOf(_resolve_annotation(args[0]), _resolve_annotation(args[1]))

    raise TypeError(
        f"Cannot infer gob type for annotation {annotation!r}. "
        "Use a primitive type (int, str, float, bool, bytes, complex, UInt, timedelta), "
        "a SemanticType registered via register_semantic_type(), "
        "a @gobstruct-decorated class, list[T], or dict[K, V]."
    )
