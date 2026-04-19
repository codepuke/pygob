"""pygob — pure-Python encoder and decoder for Go's gob binary serialization format."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from pygob.codecs import DEFAULT_CODECS, Codec
from pygob.decoder import Decoder
from pygob.encoder import Encoder
from pygob.exceptions import GobDecodeError, GobEncodeError, GobError
from pygob.types import (
    GOB_BOOL,
    GOB_BYTES,
    GOB_COMPLEX,
    GOB_DURATION,
    GOB_FLOAT,
    GOB_INT,
    GOB_INTERFACE,
    GOB_STRING,
    GOB_UINT,
    ArrayOf,
    GobEncoded,
    GobStruct,
    MapOf,
    Schema,
    SemanticType,
    SliceOf,
    UInt,
    gobstruct,
    register_semantic_type,
)

__all__ = [
    # Core classes
    "Encoder",
    "Decoder",
    "Schema",
    "GobStruct",
    "UInt",
    "GobEncoded",
    "gobstruct",
    # Semantic type aliases (named primitives)
    "SemanticType",
    "register_semantic_type",
    # Collection type descriptors
    "SliceOf",
    "MapOf",
    "ArrayOf",
    # Type constants
    "GOB_BOOL",
    "GOB_BYTES",
    "GOB_COMPLEX",
    "GOB_DURATION",
    "GOB_FLOAT",
    "GOB_INT",
    "GOB_INTERFACE",
    "GOB_STRING",
    "GOB_UINT",
    # Exceptions
    "GobError",
    "GobDecodeError",
    "GobEncodeError",
    # Codecs
    "Codec",
    "DEFAULT_CODECS",
    # Convenience functions
    "encode",
    "decode",
]


def encode(
    value: Any,
    *,
    schema: "Schema | None" = None,
    elem_type: Any = None,
    key_type: Any = None,
    array_length: "int | None" = None,
    codecs: "dict | None" = None,
) -> bytes:
    """Encode *value* to gob bytes.

    Creates a one-shot :class:`Encoder` backed by a :class:`~io.BytesIO` buffer.

    Args:
        value: The Python value to encode.  May be a scalar, a
            ``GobStruct``, a ``@gobstruct``-decorated dataclass, a list,
            or a dict.
        schema: Optional :class:`Schema` when encoding a plain dict as a
            struct.  Required when *value* is a ``dict`` and the gob type
            cannot be inferred from the value alone.
        elem_type: Element type hint for list/dict values (e.g. ``GOB_INT``
            or a ``SliceOf``/``Schema``).  Required when encoding an empty
            list or dict.
        key_type: Key type hint for dict values.  Required when encoding an
            empty dict.
        array_length: When set, encode a list as a fixed-size gob array of
            this length rather than a slice.
        codecs: Optional ``dict[str, Codec]`` of built-in or custom codecs
            to install on the encoder (e.g. ``pygob.DEFAULT_CODECS``).

    Returns:
        The encoded gob bytes (including all necessary type definitions).
    """
    buf = BytesIO()
    enc = Encoder(buf, codecs=codecs)
    enc.encode(value, schema=schema, elem_type=elem_type, key_type=key_type,
               array_length=array_length)
    return buf.getvalue()


def decode(data: bytes, *, codecs: "dict | None" = None) -> Any:
    """Decode a gob value from *data*.

    Creates a one-shot :class:`Decoder` backed by a :class:`~io.BytesIO` buffer.

    Args:
        data: Raw gob bytes (as produced by :func:`encode` or Go's
            ``encoding/gob`` package).
        codecs: Optional ``dict[str, Codec]`` of built-in or custom codecs
            to install on the decoder (e.g. ``pygob.DEFAULT_CODECS``).

    Returns:
        The decoded Python value.

    Raises:
        GobDecodeError: if *data* is malformed or the type is unknown.
    """
    buf = BytesIO(data)
    dec = Decoder(buf, codecs=codecs)
    return dec.decode()
