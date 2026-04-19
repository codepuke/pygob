"""Tests for the public API convenience functions: pygob.encode and pygob.decode."""

from __future__ import annotations

import pygob
from pygob import (
    GOB_BOOL,
    GOB_BYTES,
    GOB_COMPLEX,
    GOB_FLOAT,
    GOB_INT,
    GOB_STRING,
    GOB_UINT,
    GobDecodeError,
    GobEncodeError,
    GobEncoded,
    GobError,
    GobStruct,
    Schema,
    UInt,
    decode,
    encode,
    gobstruct,
)


# ---------------------------------------------------------------------------
# Re-export smoke tests
# ---------------------------------------------------------------------------

def test_all_exports_present():
    """All documented names in __all__ are importable from pygob."""
    for name in pygob.__all__:
        assert hasattr(pygob, name), f"pygob.{name} not found"


def test_type_constants():
    assert GOB_INT == 2
    assert GOB_UINT == 3
    assert GOB_BOOL == 1
    assert GOB_FLOAT == 4
    assert GOB_BYTES == 5
    assert GOB_STRING == 6
    assert GOB_COMPLEX == 7


def test_exception_hierarchy():
    assert issubclass(GobDecodeError, GobError)
    assert issubclass(GobEncodeError, GobError)


# ---------------------------------------------------------------------------
# encode / decode convenience functions
# ---------------------------------------------------------------------------

def test_encode_decode_int():
    data = encode(42)
    assert isinstance(data, bytes)
    assert decode(data) == 42


def test_encode_decode_bool():
    assert decode(encode(True)) is True
    assert decode(encode(False)) is False


def test_encode_decode_float():
    result = decode(encode(3.14))
    assert abs(result - 3.14) < 1e-10


def test_encode_decode_string():
    assert decode(encode("hello, 世界")) == "hello, 世界"


def test_encode_decode_bytes():
    assert decode(encode(b"raw bytes")) == b"raw bytes"


def test_encode_decode_complex():
    assert decode(encode(1 + 2j)) == 1 + 2j


def test_encode_decode_uint():
    assert decode(encode(UInt(255))) == 255


def test_encode_decode_struct_via_schema():
    schema = Schema("Point", X=GOB_INT, Y=GOB_INT)
    data = encode({"X": 22, "Y": 33}, schema=schema)
    result = decode(data)
    assert isinstance(result, GobStruct)
    assert result["X"] == 22
    assert result["Y"] == 33
    assert result.gob_type == "Point"


def test_encode_decode_list():
    assert decode(encode([1, 2, 3])) == [1, 2, 3]


def test_encode_decode_empty_string():
    assert decode(encode("")) == ""


def test_encode_returns_bytes():
    result = encode(0)
    assert isinstance(result, bytes)
