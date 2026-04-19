"""Tests for pygob.codecs: built-in TimeCodec, UUIDCodec, DEFAULT_CODECS, and duration helpers."""

from __future__ import annotations

import io
import struct
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import pygob
from pygob.codecs import (
    DEFAULT_CODECS,
    Codec,
    TimeCodec,
    UUIDCodec,
    duration_to_timedelta,
    timedelta_to_duration,
)
from pygob.decoder import Decoder
from pygob.encoder import Encoder
from pygob.types import GobEncoded, GobStruct, Schema
from pygob.wire import INT, STRING

TESTDATA = Path(__file__).parent / "testdata"


def _load_gob(name: str) -> bytes:
    return (TESTDATA / f"{name}.gob").read_bytes()


# ---------------------------------------------------------------------------
# Codec dataclass
# ---------------------------------------------------------------------------


def test_codec_dataclass_fields():
    """Codec holds callable encode and decode attributes."""
    c = Codec(decode=lambda b: b, encode=lambda v: v)
    assert callable(c.decode)
    assert callable(c.encode)


def test_default_codecs_keys():
    """DEFAULT_CODECS contains 'Time' and 'UUID' keys."""
    assert "Time" in DEFAULT_CODECS
    assert "UUID" in DEFAULT_CODECS
    for codec in DEFAULT_CODECS.values():
        assert isinstance(codec, Codec)


# ---------------------------------------------------------------------------
# TimeCodec decode
# ---------------------------------------------------------------------------


def test_time_codec_decode_from_fixture():
    """TimeCodec.decode converts the scalar_time fixture to the expected datetime."""
    data = _load_gob("scalar_time")
    dec = Decoder(io.BytesIO(data))
    dec.register_codec("Time", TimeCodec.decode)
    result = dec.decode()

    expected = datetime(2009, 11, 10, 23, 0, 0, tzinfo=timezone.utc)
    assert result == expected


def test_time_codec_decode_utc_sentinel():
    """offset_min == -1 is decoded as UTC timezone."""
    # Build a 15-byte payload for 1970-01-01 00:00:00 UTC
    sec_since_y1 = 62135596800  # Unix epoch in year-1 seconds
    payload = (
        struct.pack("B", 1)
        + struct.pack(">q", sec_since_y1)
        + struct.pack(">i", 0)
        + struct.pack(">h", -1)  # UTC sentinel
    )
    result = TimeCodec.decode(payload)
    assert result.tzinfo == timezone.utc
    assert result == datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_time_codec_decode_non_utc_offset():
    """Non-UTC offset_min produces the correct timezone."""
    sec_since_y1 = 62135596800 + 3600  # 1970-01-01 01:00:00 +01:00 → UTC 00:00:00
    payload = (
        struct.pack("B", 1)
        + struct.pack(">q", sec_since_y1)
        + struct.pack(">i", 0)
        + struct.pack(">h", 60)  # +01:00
    )
    result = TimeCodec.decode(payload)
    assert result.utcoffset() == timedelta(hours=1)


def test_time_codec_decode_wrong_length():
    """TimeCodec.decode raises ValueError for non-15-byte payloads."""
    with pytest.raises(ValueError, match="15 bytes"):
        TimeCodec.decode(b"\x01" * 10)


def test_time_codec_decode_wrong_version():
    """TimeCodec.decode raises ValueError for unknown version byte."""
    payload = struct.pack("B", 99) + b"\x00" * 14
    with pytest.raises(ValueError, match="version"):
        TimeCodec.decode(payload)


# ---------------------------------------------------------------------------
# TimeCodec encode
# ---------------------------------------------------------------------------


def test_time_codec_roundtrip():
    """Encode then decode a datetime returns the original value."""
    dt = datetime(2023, 6, 15, 12, 30, 45, tzinfo=timezone.utc)
    encoded = TimeCodec.encode(dt)
    assert len(encoded) == 15
    decoded = TimeCodec.decode(encoded)
    assert decoded == dt


def test_time_codec_encode_naive_treated_as_utc():
    """Naive datetime is encoded as UTC (sentinel -1)."""
    dt_naive = datetime(2000, 1, 1, 0, 0, 0)
    encoded = TimeCodec.encode(dt_naive)
    offset_min = struct.unpack(">h", encoded[13:15])[0]
    assert offset_min == -1


def test_time_codec_encode_microseconds_preserved():
    """Microseconds round-trip correctly (nanoseconds are truncated to microseconds)."""
    dt = datetime(2023, 6, 15, 12, 30, 45, 123456, tzinfo=timezone.utc)
    encoded = TimeCodec.encode(dt)
    decoded = TimeCodec.decode(encoded)
    assert decoded.microsecond == 123456


# ---------------------------------------------------------------------------
# TimeCodec via Decoder(codecs=...) constructor kwarg
# ---------------------------------------------------------------------------


def test_decoder_codecs_kwarg_time():
    """Decoder(codecs=DEFAULT_CODECS) auto-decodes time.Time to datetime."""
    data = _load_gob("scalar_time")
    dec = Decoder(io.BytesIO(data), codecs=DEFAULT_CODECS)
    result = dec.decode()
    assert isinstance(result, datetime)
    assert result == datetime(2009, 11, 10, 23, 0, 0, tzinfo=timezone.utc)


def test_decoder_codecs_kwarg_selective():
    """Decoder accepts a selective codec dict (only Time, not UUID)."""
    from pygob.codecs import TimeCodec
    data = _load_gob("scalar_time")
    dec = Decoder(io.BytesIO(data), codecs={"Time": Codec(decode=TimeCodec.decode, encode=TimeCodec.encode)})
    result = dec.decode()
    assert isinstance(result, datetime)


def test_decoder_codecs_kwarg_none_is_gob_encoded():
    """Without codecs=, time.Time decodes to GobEncoded (unchanged default behavior)."""
    data = _load_gob("scalar_time")
    dec = Decoder(io.BytesIO(data))
    result = dec.decode()
    assert isinstance(result, GobEncoded)


# ---------------------------------------------------------------------------
# pygob.decode() convenience function with codecs=
# ---------------------------------------------------------------------------


def test_decode_convenience_codecs_kwarg():
    """pygob.decode(data, codecs=DEFAULT_CODECS) decodes time.Time automatically."""
    data = _load_gob("scalar_time")
    result = pygob.decode(data, codecs=DEFAULT_CODECS)
    assert isinstance(result, datetime)


# ---------------------------------------------------------------------------
# UUIDCodec decode
# ---------------------------------------------------------------------------

TEST_UUID = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
TEST_UUID_BYTES = TEST_UUID.bytes


def test_uuid_codec_decode_from_fixture():
    """UUIDCodec.decode converts the scalar_uuid fixture to the expected uuid.UUID."""
    data = _load_gob("scalar_uuid")
    dec = Decoder(io.BytesIO(data), codecs=DEFAULT_CODECS)
    result = dec.decode()
    assert isinstance(result, uuid.UUID)
    assert result == TEST_UUID


def test_uuid_codec_decode_raw():
    """UUIDCodec.decode converts 16 bytes to uuid.UUID."""
    result = UUIDCodec.decode(TEST_UUID_BYTES)
    assert result == TEST_UUID


def test_uuid_codec_decode_wrong_length():
    """UUIDCodec.decode raises ValueError for non-16-byte payloads."""
    with pytest.raises(ValueError, match="16 bytes"):
        UUIDCodec.decode(b"\x00" * 10)


# ---------------------------------------------------------------------------
# UUIDCodec encode
# ---------------------------------------------------------------------------


def test_uuid_codec_encode():
    """UUIDCodec.encode produces the 16-byte representation."""
    result = UUIDCodec.encode(TEST_UUID)
    assert result == TEST_UUID_BYTES
    assert len(result) == 16


def test_uuid_codec_roundtrip():
    """Encode then decode returns the original UUID."""
    encoded = UUIDCodec.encode(TEST_UUID)
    decoded = UUIDCodec.decode(encoded)
    assert decoded == TEST_UUID


# ---------------------------------------------------------------------------
# Encoder codecs= kwarg
# ---------------------------------------------------------------------------


def test_encoder_codecs_kwarg_time(go_verify):
    """Encoder(codecs=DEFAULT_CODECS) encodes datetime → Go can decode as time.Time."""
    dt = datetime(2009, 11, 10, 23, 0, 0, tzinfo=timezone.utc)
    buf = io.BytesIO()
    enc = Encoder(buf, codecs=DEFAULT_CODECS)
    enc.encode_gob_encoded(dt, "Time")
    gob_bytes = buf.getvalue()

    result = go_verify("scalar_time", gob_bytes)
    assert result["ok"] is True
    assert result["value"]["unix"] == 1257894000


def test_encoder_codecs_kwarg_uuid(go_verify):
    """Encoder(codecs=DEFAULT_CODECS) encodes uuid.UUID → Go can decode it."""
    buf = io.BytesIO()
    enc = Encoder(buf, codecs=DEFAULT_CODECS)
    enc.encode_gob_encoded(TEST_UUID, "UUID")
    gob_bytes = buf.getvalue()

    result = go_verify("scalar_uuid", gob_bytes)
    assert result["ok"] is True
    assert result["value"] == str(TEST_UUID)


def test_encode_decode_roundtrip_time_via_gob_encoded():
    """Encode a datetime as GobEncoded then decode back with TimeCodec gives original value."""
    dt = datetime(2009, 11, 10, 23, 0, 0, tzinfo=timezone.utc)
    ge = GobEncoded("Time", TimeCodec.encode(dt))
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode_gob_encoded(ge, "Time")
    result = pygob.decode(buf.getvalue(), codecs={"Time": DEFAULT_CODECS["Time"]})
    assert isinstance(result, datetime)
    assert result == dt


# ---------------------------------------------------------------------------
# duration helpers
# ---------------------------------------------------------------------------


def test_duration_to_timedelta_basic():
    """1 second = 1_000_000_000 nanoseconds."""
    td = duration_to_timedelta(1_000_000_000)
    assert td == timedelta(seconds=1)


def test_duration_to_timedelta_microsecond_truncation():
    """Sub-microsecond nanoseconds are truncated."""
    td = duration_to_timedelta(1_500)  # 1.5 microseconds
    assert td == timedelta(microseconds=1)


def test_timedelta_to_duration_basic():
    """1 second timedelta = 1_000_000_000 nanoseconds."""
    ns = timedelta_to_duration(timedelta(seconds=1))
    assert ns == 1_000_000_000


def test_timedelta_to_duration_roundtrip():
    """Round-trip timedelta → ns → timedelta (within microsecond precision)."""
    td = timedelta(hours=2, minutes=30, seconds=15, microseconds=500000)
    ns = timedelta_to_duration(td)
    result = duration_to_timedelta(ns)
    assert result == td
