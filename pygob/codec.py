"""Low-level encode/decode for gob primitive types: unsigned ints, signed ints, floats, etc."""

from __future__ import annotations

import struct
from io import BytesIO
from typing import Union

from pygob.exceptions import GobDecodeError, GobEncodeError

_BufType = Union[bytes, bytearray, BytesIO]


def encode_uint(x: int) -> bytes:
    """Encode x as a gob unsigned integer.

    Encoding rules:
    - Values 0–127: single byte equal to the value.
    - Values >= 128: one header byte equal to (256 - byte_count), followed by
      the value's big-endian minimal byte representation.
    """
    if x < 0:
        raise GobEncodeError(f"encode_uint: negative value {x!r}")
    if x < 128:
        return bytes([x])
    n = (x.bit_length() + 7) // 8
    return bytes([256 - n]) + x.to_bytes(n, "big")


def encode_int(x: int) -> bytes:
    """Encode x as a gob signed integer using zigzag encoding.

    Zigzag maps signed integers to unsigned:
      0 → 0, -1 → 1, 1 → 2, -2 → 3, 2 → 4, …
    Then the unsigned value is encoded with encode_uint.
    """
    u = (~x << 1) | 1 if x < 0 else x << 1
    return encode_uint(u)


def decode_int(buf: _BufType) -> tuple[int, int]:
    """Decode a gob signed integer from *buf*.

    Reverses zigzag encoding.  Returns ``(value, bytes_consumed)``.
    """
    u, n = decode_uint(buf)
    if u & 1:
        return ~(u >> 1), n
    return u >> 1, n


def decode_uint(buf: _BufType) -> tuple[int, int]:
    """Decode a gob unsigned integer from *buf*.

    *buf* may be a ``bytes``/``bytearray`` object or any readable binary
    stream (e.g. ``BytesIO``).  Returns ``(value, bytes_consumed)``.
    """
    if hasattr(buf, "read"):
        raw = buf.read(1)
        if not raw:
            raise GobDecodeError("decode_uint: unexpected end of stream")
        b = raw[0]
        if b < 128:
            return b, 1
        count = 256 - b
        data = buf.read(count)
        if len(data) < count:
            raise GobDecodeError("decode_uint: truncated stream")
        return int.from_bytes(data, "big"), 1 + count
    else:
        if not buf:
            raise GobDecodeError("decode_uint: empty buffer")
        b = buf[0]
        if b < 128:
            return b, 1
        count = 256 - b
        if len(buf) < 1 + count:
            raise GobDecodeError("decode_uint: buffer too short")
        return int.from_bytes(buf[1 : 1 + count], "big"), 1 + count


def encode_float(x: float) -> bytes:
    """Encode x as a gob float64.

    IEEE 754 big-endian bytes are reversed (exponent last → first), then the
    resulting 8-byte little-endian value is encoded as an unsigned integer.
    This makes zero encode as a single 0x00 byte and allows trailing zero
    compression for small exponents.
    """
    raw = struct.pack(">d", x)      # 8 bytes, big-endian IEEE 754
    u = int.from_bytes(raw[::-1], "big")   # byte-reverse, interpret as uint
    return encode_uint(u)


def decode_float(buf: _BufType) -> tuple[float, int]:
    """Decode a gob float64 from *buf*.

    Reverses the encoding: decode uint, convert to 8 bytes, byte-reverse to
    recover big-endian IEEE 754, unpack as float64.  Returns
    ``(value, bytes_consumed)``.
    """
    u, n = decode_uint(buf)
    reversed_bytes = u.to_bytes(8, "big")   # big-endian of the reversed value
    ieee_bytes = reversed_bytes[::-1]        # restore big-endian IEEE 754 order
    (x,) = struct.unpack(">d", ieee_bytes)
    return x, n


def encode_complex(x: complex) -> bytes:
    """Encode *x* as a gob complex128 (real part followed by imaginary part)."""
    return encode_float(x.real) + encode_float(x.imag)


def decode_complex(buf: _BufType) -> tuple[complex, int]:
    """Decode a gob complex128 from *buf*.

    Returns ``(value, bytes_consumed)``.
    """
    if not hasattr(buf, "read"):
        buf = BytesIO(buf)
    real, n1 = decode_float(buf)
    imag, n2 = decode_float(buf)
    return complex(real, imag), n1 + n2


def encode_bool(x: bool) -> bytes:
    """Encode *x* as a gob bool (unsigned int 0 or 1)."""
    return encode_uint(1 if x else 0)


def decode_bool(buf: _BufType) -> tuple[bool, int]:
    """Decode a gob bool from *buf*.

    Returns ``(value, bytes_consumed)``.
    """
    u, n = decode_uint(buf)
    return bool(u), n


def encode_string(x: str) -> bytes:
    """Encode *x* as a gob string (uint length prefix + raw UTF-8 bytes)."""
    raw = x.encode("utf-8")
    return encode_uint(len(raw)) + raw


def decode_string(buf: _BufType) -> tuple[str, int]:
    """Decode a gob string from *buf*.

    Returns ``(value, bytes_consumed)``.
    """
    if not hasattr(buf, "read"):
        buf = BytesIO(buf)
    length, n = decode_uint(buf)
    raw = buf.read(length)
    if len(raw) < length:
        raise GobDecodeError("decode_string: truncated stream")
    return raw.decode("utf-8"), n + length


def encode_bytes(x: bytes) -> bytes:
    """Encode *x* as a gob []byte (uint length prefix + raw bytes)."""
    return encode_uint(len(x)) + x


def decode_bytes(buf: _BufType) -> tuple[bytes, int]:
    """Decode a gob []byte from *buf*.

    Returns ``(value, bytes_consumed)``.
    """
    if not hasattr(buf, "read"):
        buf = BytesIO(buf)
    length, n = decode_uint(buf)
    raw = buf.read(length)
    if len(raw) < length:
        raise GobDecodeError("decode_bytes: truncated stream")
    return raw, n + length


class CodecReader:
    """Stream-oriented reader that decodes gob primitives from a BytesIO."""

    def __init__(self, stream: BytesIO) -> None:
        self._stream = stream

    def read_uint(self) -> int:
        """Read and return one gob unsigned integer."""
        value, _ = decode_uint(self._stream)
        return value

    def read_int(self) -> int:
        """Read and return one gob signed integer."""
        value, _ = decode_int(self._stream)
        return value

    def read_float(self) -> float:
        """Read and return one gob float64."""
        value, _ = decode_float(self._stream)
        return value

    def read_complex(self) -> complex:
        """Read and return one gob complex128."""
        value, _ = decode_complex(self._stream)
        return value

    def read_bool(self) -> bool:
        """Read and return one gob bool."""
        value, _ = decode_bool(self._stream)
        return value

    def read_string(self) -> str:
        """Read and return one gob string."""
        value, _ = decode_string(self._stream)
        return value

    def read_bytes_value(self) -> bytes:
        """Read and return one gob []byte."""
        value, _ = decode_bytes(self._stream)
        return value

    def read_raw(self, n: int) -> bytes:
        """Read exactly *n* raw bytes from the stream."""
        data = self._stream.read(n)
        if len(data) < n:
            raise GobDecodeError(f"read_raw: expected {n} bytes, got {len(data)}")
        return data


class CodecWriter:
    """Stream-oriented writer that encodes gob primitives into a BytesIO."""

    def __init__(self) -> None:
        self._stream = BytesIO()

    def write_uint(self, x: int) -> None:
        """Write one gob unsigned integer."""
        self._stream.write(encode_uint(x))

    def write_int(self, x: int) -> None:
        """Write one gob signed integer."""
        self._stream.write(encode_int(x))

    def write_float(self, x: float) -> None:
        """Write one gob float64."""
        self._stream.write(encode_float(x))

    def write_complex(self, x: complex) -> None:
        """Write one gob complex128."""
        self._stream.write(encode_complex(x))

    def write_bool(self, x: bool) -> None:
        """Write one gob bool."""
        self._stream.write(encode_bool(x))

    def write_string(self, x: str) -> None:
        """Write one gob string."""
        self._stream.write(encode_string(x))

    def write_bytes_value(self, x: bytes) -> None:
        """Write one gob []byte."""
        self._stream.write(encode_bytes(x))

    def write_raw(self, data: bytes) -> None:
        """Write raw bytes directly to the stream."""
        self._stream.write(data)

    def getvalue(self) -> bytes:
        """Return all bytes written so far."""
        return self._stream.getvalue()
