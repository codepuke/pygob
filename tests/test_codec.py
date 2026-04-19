"""Tests for pygob/codec.py — Tasks 1.1–1.5: unsigned/signed int, float, complex, bool, string, bytes, stream helpers."""

from __future__ import annotations

import math
import struct
from io import BytesIO

import pytest

from pygob.codec import (
    CodecReader,
    CodecWriter,
    decode_bool,
    decode_bytes,
    decode_complex,
    decode_float,
    decode_int,
    decode_string,
    decode_uint,
    encode_bool,
    encode_bytes,
    encode_complex,
    encode_float,
    encode_int,
    encode_string,
    encode_uint,
)
from pygob.exceptions import GobDecodeError, GobEncodeError

# ---------------------------------------------------------------------------
# Go's encodeT test vectors for unsigned integers (from encoding/gob tests)
# ---------------------------------------------------------------------------

ENCODE_VECTORS: list[tuple[int, bytes]] = [
    (0,                  bytes([0x00])),
    (1,                  bytes([0x01])),
    (2,                  bytes([0x02])),
    (15,                 bytes([0x0F])),
    (127,                bytes([0x7F])),
    (128,                bytes([0xFF, 0x80])),
    (255,                bytes([0xFF, 0xFF])),
    (256,                bytes([0xFE, 0x01, 0x00])),
    (4294967295,         bytes([0xFC, 0xFF, 0xFF, 0xFF, 0xFF])),  # 1<<32 - 1
    (1 << 63,            bytes([0xF8, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
]


class TestEncodeUint:
    @pytest.mark.parametrize("value,expected", ENCODE_VECTORS)
    def test_known_vectors(self, value: int, expected: bytes) -> None:
        assert encode_uint(value) == expected

    def test_negative_raises(self) -> None:
        with pytest.raises(GobEncodeError):
            encode_uint(-1)

    def test_large_negative_raises(self) -> None:
        with pytest.raises(GobEncodeError):
            encode_uint(-(2**64))


class TestDecodeUint:
    @pytest.mark.parametrize("expected,buf", ENCODE_VECTORS)
    def test_known_vectors_bytes(self, expected: int, buf: bytes) -> None:
        value, consumed = decode_uint(buf)
        assert value == expected
        assert consumed == len(buf)

    @pytest.mark.parametrize("expected,buf", ENCODE_VECTORS)
    def test_known_vectors_bytearray(self, expected: int, buf: bytes) -> None:
        value, consumed = decode_uint(bytearray(buf))
        assert value == expected
        assert consumed == len(buf)

    @pytest.mark.parametrize("expected,buf", ENCODE_VECTORS)
    def test_known_vectors_bytesio(self, expected: int, buf: bytes) -> None:
        stream = BytesIO(buf)
        value, consumed = decode_uint(stream)
        assert value == expected
        assert consumed == len(buf)
        # Stream position advanced correctly
        assert stream.tell() == len(buf)

    def test_extra_bytes_not_consumed(self) -> None:
        """Bytes after the encoded uint are left untouched (bytes input)."""
        buf = bytes([0x0F, 0xAA, 0xBB])
        value, consumed = decode_uint(buf)
        assert value == 15
        assert consumed == 1

    def test_extra_bytes_not_consumed_stream(self) -> None:
        """Stream position stops after the encoded uint."""
        stream = BytesIO(bytes([0xFF, 0x80, 0xAA]))
        value, consumed = decode_uint(stream)
        assert value == 128
        assert consumed == 2
        assert stream.tell() == 2

    def test_empty_bytes_raises(self) -> None:
        with pytest.raises(GobDecodeError):
            decode_uint(b"")

    def test_truncated_bytes_raises(self) -> None:
        # Header says 2 bytes follow, but only 1 is present
        with pytest.raises(GobDecodeError):
            decode_uint(bytes([0xFE, 0x01]))

    def test_empty_stream_raises(self) -> None:
        with pytest.raises(GobDecodeError):
            decode_uint(BytesIO(b""))

    def test_truncated_stream_raises(self) -> None:
        with pytest.raises(GobDecodeError):
            decode_uint(BytesIO(bytes([0xFE, 0x01])))


# ---------------------------------------------------------------------------
# Signed integer test vectors (Task 1.2)
# ---------------------------------------------------------------------------

ENCODE_INT_VECTORS: list[tuple[int, bytes]] = [
    (0,    bytes([0x00])),
    (1,    bytes([0x02])),
    (-1,   bytes([0x01])),
    (22,   bytes([0x2C])),
    (33,   bytes([0x42])),
    (-129, bytes([0xFE, 0x01, 0x01])),
]


class TestEncodeInt:
    @pytest.mark.parametrize("value,expected", ENCODE_INT_VECTORS)
    def test_known_vectors(self, value: int, expected: bytes) -> None:
        assert encode_int(value) == expected


class TestDecodeInt:
    @pytest.mark.parametrize("expected,buf", ENCODE_INT_VECTORS)
    def test_known_vectors_bytes(self, expected: int, buf: bytes) -> None:
        value, consumed = decode_int(buf)
        assert value == expected
        assert consumed == len(buf)

    @pytest.mark.parametrize("expected,buf", ENCODE_INT_VECTORS)
    def test_known_vectors_bytesio(self, expected: int, buf: bytes) -> None:
        stream = BytesIO(buf)
        value, consumed = decode_int(stream)
        assert value == expected
        assert consumed == len(buf)
        assert stream.tell() == len(buf)


class TestRoundTripInt:
    @pytest.mark.parametrize("value", [
        0, 1, -1, 127, -127, 128, -128, 255, -255, 256, -256,
        2**32, -(2**32), 2**62, -(2**62),
    ])
    def test_standard_values(self, value: int) -> None:
        decoded, _ = decode_int(encode_int(value))
        assert decoded == value

    def test_large_positive(self) -> None:
        value = 2**100
        assert decode_int(encode_int(value))[0] == value

    def test_large_negative(self) -> None:
        value = -(2**100)
        assert decode_int(encode_int(value))[0] == value


class TestRoundTrip:
    @pytest.mark.parametrize("value", [
        0, 1, 127, 128, 255, 256, 2**32, 2**64 - 1,
    ])
    def test_standard_values(self, value: int) -> None:
        assert decode_uint(encode_uint(value))[0] == value

    def test_arbitrary_precision_above_64bit(self) -> None:
        """Python's arbitrary precision: encode/decode values > 2**64."""
        for value in [2**64, 2**64 + 1, 2**128, 2**256 - 1]:
            encoded = encode_uint(value)
            decoded, consumed = decode_uint(encoded)
            assert decoded == value
            assert consumed == len(encoded)


# ---------------------------------------------------------------------------
# Float encode/decode (Task 1.3)
# ---------------------------------------------------------------------------

FLOAT_ENCODE_VECTORS: list[tuple[float, bytes]] = [
    (0.0,  bytes([0x00])),
    (17.0, bytes([0xFE, 0x31, 0x40])),
]


class TestEncodeFloat:
    @pytest.mark.parametrize("value,expected", FLOAT_ENCODE_VECTORS)
    def test_known_vectors(self, value: float, expected: bytes) -> None:
        assert encode_float(value) == expected

    def test_byte_reversal_logic(self) -> None:
        """encode_float reverses struct.pack('>d', x) before encoding as uint."""
        for x in [3.14159, -1e100, 17.0, 0.0]:
            big_endian = struct.pack(">d", x)
            u = int.from_bytes(big_endian[::-1], "big")
            from pygob.codec import encode_uint
            assert encode_float(x) == encode_uint(u)


class TestDecodeFloat:
    @pytest.mark.parametrize("expected,buf", FLOAT_ENCODE_VECTORS)
    def test_known_vectors_bytes(self, expected: float, buf: bytes) -> None:
        value, consumed = decode_float(buf)
        assert value == expected
        assert consumed == len(buf)

    @pytest.mark.parametrize("expected,buf", FLOAT_ENCODE_VECTORS)
    def test_known_vectors_bytesio(self, expected: float, buf: bytes) -> None:
        stream = BytesIO(buf)
        value, consumed = decode_float(stream)
        assert value == expected
        assert consumed == len(buf)
        assert stream.tell() == len(buf)


class TestRoundTripFloat:
    @pytest.mark.parametrize("value", [3.14159, -1e100, 1.0, -1.0, 1.5, 1e308])
    def test_finite_values(self, value: float) -> None:
        decoded, _ = decode_float(encode_float(value))
        assert decoded == value

    def test_zero(self) -> None:
        decoded, _ = decode_float(encode_float(0.0))
        assert decoded == 0.0

    def test_negative_zero(self) -> None:
        decoded, _ = decode_float(encode_float(-0.0))
        assert math.copysign(1.0, decoded) == -1.0

    def test_inf(self) -> None:
        for val in [math.inf, -math.inf]:
            decoded, _ = decode_float(encode_float(val))
            assert decoded == val

    def test_nan(self) -> None:
        decoded, _ = decode_float(encode_float(float("nan")))
        assert math.isnan(decoded)


# ---------------------------------------------------------------------------
# Complex encode/decode (Task 1.4)
# ---------------------------------------------------------------------------

class TestEncodeComplex:
    def test_zero(self) -> None:
        # complex(0,0) → two floats both zero → two 0x00 bytes
        assert encode_complex(0+0j) == bytes([0x00, 0x00])

    def test_real_only(self) -> None:
        # real=1.0, imag=0.0
        encoded = encode_complex(1+0j)
        assert encoded == encode_float(1.0) + encode_float(0.0)

    def test_both_parts(self) -> None:
        encoded = encode_complex(3.0+4.0j)
        assert encoded == encode_float(3.0) + encode_float(4.0)

    def test_negative_imag(self) -> None:
        encoded = encode_complex(1.0-2.5j)
        assert encoded == encode_float(1.0) + encode_float(-2.5)


class TestDecodeComplex:
    def test_zero(self) -> None:
        value, consumed = decode_complex(bytes([0x00, 0x00]))
        assert value == 0+0j
        assert consumed == 2

    def test_round_trip_bytes(self) -> None:
        for z in [0+0j, 1+0j, 0+1j, 1+2j, -3.5+4.5j]:
            decoded, _ = decode_complex(encode_complex(z))
            assert decoded == z

    def test_round_trip_stream(self) -> None:
        z = 3.14+2.71j
        stream = BytesIO(encode_complex(z))
        decoded, consumed = decode_complex(stream)
        assert decoded == z
        assert stream.tell() == consumed

    def test_extra_bytes_left_in_stream(self) -> None:
        data = encode_complex(1+2j) + b"\xff"
        stream = BytesIO(data)
        value, consumed = decode_complex(stream)
        assert value == 1+2j
        assert stream.tell() == consumed
        assert stream.read() == b"\xff"


# ---------------------------------------------------------------------------
# Bool encode/decode (Task 1.4)
# ---------------------------------------------------------------------------

class TestEncodeBool:
    def test_true(self) -> None:
        assert encode_bool(True) == bytes([0x01])

    def test_false(self) -> None:
        assert encode_bool(False) == bytes([0x00])


class TestDecodeBool:
    def test_true(self) -> None:
        value, consumed = decode_bool(bytes([0x01]))
        assert value is True
        assert consumed == 1

    def test_false(self) -> None:
        value, consumed = decode_bool(bytes([0x00]))
        assert value is False
        assert consumed == 1

    def test_round_trip(self) -> None:
        for b in [True, False]:
            decoded, _ = decode_bool(encode_bool(b))
            assert decoded == b

    def test_stream(self) -> None:
        stream = BytesIO(encode_bool(True))
        value, _ = decode_bool(stream)
        assert value is True


# ---------------------------------------------------------------------------
# String encode/decode (Task 1.4)
# ---------------------------------------------------------------------------

class TestEncodeString:
    def test_empty(self) -> None:
        assert encode_string("") == bytes([0x00])

    def test_ascii(self) -> None:
        # "hi" = 2 bytes → length prefix 0x02 + b"hi"
        assert encode_string("hi") == bytes([0x02]) + b"hi"

    def test_multibyte_unicode(self) -> None:
        s = "hello, 世界"
        raw = s.encode("utf-8")
        encoded = encode_string(s)
        length, n = decode_uint(encoded)
        assert length == len(raw)
        assert encoded[n:] == raw

    def test_long_string(self) -> None:
        s = "x" * 200
        encoded = encode_string(s)
        decoded, _ = decode_string(encoded)
        assert decoded == s


class TestDecodeString:
    def test_empty(self) -> None:
        value, consumed = decode_string(bytes([0x00]))
        assert value == ""
        assert consumed == 1

    def test_ascii(self) -> None:
        value, consumed = decode_string(bytes([0x02]) + b"hi")
        assert value == "hi"
        assert consumed == 3

    def test_round_trip(self) -> None:
        for s in ["", "hello", "hello, 世界", "a" * 300]:
            decoded, _ = decode_string(encode_string(s))
            assert decoded == s

    def test_stream(self) -> None:
        s = "world"
        stream = BytesIO(encode_string(s))
        value, consumed = decode_string(stream)
        assert value == s
        assert stream.tell() == consumed

    def test_truncated_raises(self) -> None:
        from pygob.exceptions import GobDecodeError
        # length says 5 but only 2 bytes follow
        buf = BytesIO(encode_uint(5) + b"ab")
        with pytest.raises(GobDecodeError):
            decode_string(buf)


# ---------------------------------------------------------------------------
# Bytes encode/decode (Task 1.4)
# ---------------------------------------------------------------------------

class TestEncodeBytes:
    def test_empty(self) -> None:
        assert encode_bytes(b"") == bytes([0x00])

    def test_simple(self) -> None:
        assert encode_bytes(b"hi") == bytes([0x02]) + b"hi"

    def test_long(self) -> None:
        data = bytes(range(256))
        encoded = encode_bytes(data)
        decoded, _ = decode_bytes(encoded)
        assert decoded == data


class TestDecodeBytes:
    def test_empty(self) -> None:
        value, consumed = decode_bytes(bytes([0x00]))
        assert value == b""
        assert consumed == 1

    def test_simple(self) -> None:
        value, consumed = decode_bytes(bytes([0x02]) + b"hi")
        assert value == b"hi"
        assert consumed == 3

    def test_round_trip(self) -> None:
        for data in [b"", b"hello", bytes(range(256))]:
            decoded, _ = decode_bytes(encode_bytes(data))
            assert decoded == data

    def test_stream(self) -> None:
        data = b"test"
        stream = BytesIO(encode_bytes(data))
        value, consumed = decode_bytes(stream)
        assert value == data
        assert stream.tell() == consumed

    def test_truncated_raises(self) -> None:
        from pygob.exceptions import GobDecodeError
        buf = BytesIO(encode_uint(5) + b"ab")
        with pytest.raises(GobDecodeError):
            decode_bytes(buf)


# ---------------------------------------------------------------------------
# CodecReader / CodecWriter stream helpers (Task 1.5)
# ---------------------------------------------------------------------------

class TestCodecWriter:
    def test_write_uint(self) -> None:
        w = CodecWriter()
        w.write_uint(128)
        assert w.getvalue() == encode_uint(128)

    def test_write_int(self) -> None:
        w = CodecWriter()
        w.write_int(-1)
        assert w.getvalue() == encode_int(-1)

    def test_write_float(self) -> None:
        w = CodecWriter()
        w.write_float(3.14)
        assert w.getvalue() == encode_float(3.14)

    def test_write_complex(self) -> None:
        w = CodecWriter()
        w.write_complex(1+2j)
        assert w.getvalue() == encode_complex(1+2j)

    def test_write_bool(self) -> None:
        w = CodecWriter()
        w.write_bool(True)
        assert w.getvalue() == encode_bool(True)

    def test_write_string(self) -> None:
        w = CodecWriter()
        w.write_string("hello")
        assert w.getvalue() == encode_string("hello")

    def test_write_bytes_value(self) -> None:
        w = CodecWriter()
        w.write_bytes_value(b"data")
        assert w.getvalue() == encode_bytes(b"data")

    def test_write_raw(self) -> None:
        w = CodecWriter()
        w.write_raw(b"\xde\xad\xbe\xef")
        assert w.getvalue() == b"\xde\xad\xbe\xef"

    def test_multiple_writes_accumulate(self) -> None:
        w = CodecWriter()
        w.write_uint(1)
        w.write_uint(2)
        assert w.getvalue() == encode_uint(1) + encode_uint(2)


class TestCodecReader:
    def test_read_uint(self) -> None:
        r = CodecReader(BytesIO(encode_uint(255)))
        assert r.read_uint() == 255

    def test_read_int(self) -> None:
        r = CodecReader(BytesIO(encode_int(-42)))
        assert r.read_int() == -42

    def test_read_float(self) -> None:
        r = CodecReader(BytesIO(encode_float(2.71)))
        assert r.read_float() == 2.71

    def test_read_complex(self) -> None:
        r = CodecReader(BytesIO(encode_complex(3+4j)))
        assert r.read_complex() == 3+4j

    def test_read_bool(self) -> None:
        r = CodecReader(BytesIO(encode_bool(False)))
        assert r.read_bool() is False

    def test_read_string(self) -> None:
        r = CodecReader(BytesIO(encode_string("world")))
        assert r.read_string() == "world"

    def test_read_bytes_value(self) -> None:
        r = CodecReader(BytesIO(encode_bytes(b"\x01\x02\x03")))
        assert r.read_bytes_value() == b"\x01\x02\x03"

    def test_read_raw(self) -> None:
        r = CodecReader(BytesIO(b"\xca\xfe\xba\xbe"))
        assert r.read_raw(4) == b"\xca\xfe\xba\xbe"

    def test_read_raw_truncated_raises(self) -> None:
        r = CodecReader(BytesIO(b"\x01"))
        with pytest.raises(GobDecodeError):
            r.read_raw(4)


class TestCodecRoundTrip:
    """Write a sequence of mixed types, then read them back."""

    def test_mixed_sequence(self) -> None:
        w = CodecWriter()
        w.write_uint(300)
        w.write_int(-99)
        w.write_float(1.5)
        w.write_bool(True)
        w.write_string("pygob")
        w.write_bytes_value(b"\xff\x00")
        w.write_complex(2-3j)
        w.write_raw(b"\xAB\xCD")

        r = CodecReader(BytesIO(w.getvalue()))
        assert r.read_uint() == 300
        assert r.read_int() == -99
        assert r.read_float() == 1.5
        assert r.read_bool() is True
        assert r.read_string() == "pygob"
        assert r.read_bytes_value() == b"\xff\x00"
        assert r.read_complex() == 2-3j
        assert r.read_raw(2) == b"\xAB\xCD"

    def test_repeated_writes_reads(self) -> None:
        values = [0, 1, 127, 128, 2**32, -(2**31)]
        w = CodecWriter()
        for v in values:
            w.write_int(v)

        r = CodecReader(BytesIO(w.getvalue()))
        for expected in values:
            assert r.read_int() == expected

    def test_empty_string_and_bytes(self) -> None:
        w = CodecWriter()
        w.write_string("")
        w.write_bytes_value(b"")
        w.write_uint(42)

        r = CodecReader(BytesIO(w.getvalue()))
        assert r.read_string() == ""
        assert r.read_bytes_value() == b""
        assert r.read_uint() == 42
