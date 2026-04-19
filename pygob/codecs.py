"""Built-in codecs for common Go types that implement GobEncoder or BinaryMarshaler.

Usage with constructor kwarg (recommended)::

    import pygob

    dec = pygob.Decoder(f, codecs=pygob.DEFAULT_CODECS)
    enc = pygob.Encoder(buf, codecs=pygob.DEFAULT_CODECS)

    # Or selectively:
    from pygob.codecs import TimeCodec
    dec = pygob.Decoder(f, codecs={"Time": TimeCodec})

Usage with register_codec (post-construction)::

    dec.register_codec("Time", TimeCodec.decode)
    enc.register_codec("Time", TimeCodec.encode)

Duration helpers (time.Duration is a plain int64 in gob — no codec needed).
For encoding, use GOB_DURATION in a schema or timedelta annotation in @gobstruct.
For decoding Go-generated gob, convert the raw int manually::

    from pygob.codecs import duration_to_timedelta, timedelta_to_duration
"""

from __future__ import annotations

import struct
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


@dataclass
class Codec:
    """A matched pair of encode and decode functions for a GobEncoder/BinaryMarshaler type.

    Pass a ``dict[str, Codec]`` to ``Decoder(..., codecs=...)`` or
    ``Encoder(..., codecs=...)`` to install codecs at construction time.

    The same dict can be passed to both sides:

        DEFAULT_CODECS = {"Time": TimeCodec, "UUID": UUIDCodec}
        dec = Decoder(f, codecs=DEFAULT_CODECS)
        enc = Encoder(buf, codecs=DEFAULT_CODECS)

    *marshaler_type* controls which gob wire type variant is emitted when
    encoding.  Match the Go implementation:

    * ``"gob"``    — type implements ``GobEncoder`` (wire field 4, the default)
    * ``"binary"`` — type implements ``encoding.BinaryMarshaler`` (wire field 5)
    * ``"text"``   — type implements ``encoding.TextMarshaler`` (wire field 6)
    """

    decode: Callable[[bytes], Any]
    encode: Callable[[Any], bytes]
    marshaler_type: str = "gob"  # "gob", "binary", or "text"


# ---------------------------------------------------------------------------
# time.Time codec
# ---------------------------------------------------------------------------

# Go's time.Time MarshalBinary format (15 bytes):
#   version   uint8  (always 1)
#   sec_y1    int64  big-endian  seconds since year 1, Jan 1, 00:00:00 UTC
#   nsec      int32  big-endian  nanoseconds [0, 999999999]
#   off_min   int16  big-endian  UTC offset in minutes; -1 means UTC
#
# Relationship to Unix epoch:
#   Unix epoch (1970-01-01) is 62135596800 seconds after year-1 epoch.

_UNIX_TO_Y1_OFFSET = 62135596800  # seconds from year-1 epoch to Unix epoch


class TimeCodec:
    """Codec for Go's time.Time (BinaryMarshaler, gob type name "Time")."""

    @staticmethod
    def decode(data: bytes) -> datetime:
        """Decode a 15-byte Go time.Time binary payload to datetime.datetime."""
        if len(data) != 15:
            raise ValueError(f"time.Time binary payload must be 15 bytes, got {len(data)}")
        version = data[0]
        if version != 1:
            raise ValueError(f"unsupported time.Time binary version {version}")
        sec_since_y1 = struct.unpack(">q", data[1:9])[0]
        nsec = struct.unpack(">i", data[9:13])[0]
        offset_min = struct.unpack(">h", data[13:15])[0]

        unix_sec = sec_since_y1 - _UNIX_TO_Y1_OFFSET
        if offset_min == -1:
            tz = timezone.utc
        else:
            tz = timezone(timedelta(minutes=offset_min))

        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        dt = epoch + timedelta(seconds=unix_sec, microseconds=nsec // 1000)
        return dt.astimezone(tz)

    @staticmethod
    def encode(dt: datetime) -> bytes:
        """Encode a datetime.datetime to a 15-byte Go time.Time binary payload.

        Note: Python datetime has only microsecond precision. Sub-microsecond
        nanoseconds cannot be represented and will be lost on a decode→encode
        round-trip of Go values that carry nanosecond precision.
        """
        if dt.tzinfo is None:
            # Treat naive datetime as UTC
            dt = dt.replace(tzinfo=timezone.utc)

        # Seconds since year-1 epoch
        epoch_y1 = datetime(1, 1, 1, tzinfo=timezone.utc)
        delta = dt.astimezone(timezone.utc) - epoch_y1
        sec_since_y1 = int(delta.total_seconds())
        # Nanoseconds — Python datetime has only microsecond precision
        nsec = dt.microsecond * 1000

        utc_offset = dt.utcoffset()
        if utc_offset is None or utc_offset == timedelta(0):
            offset_min = -1  # sentinel for UTC
        else:
            offset_min = int(utc_offset.total_seconds() / 60)

        return (
            struct.pack("B", 1)            # version
            + struct.pack(">q", sec_since_y1)  # sec since year-1
            + struct.pack(">i", nsec)          # nanoseconds
            + struct.pack(">h", offset_min)    # UTC offset minutes
        )


# ---------------------------------------------------------------------------
# UUID codec
# ---------------------------------------------------------------------------

class UUIDCodec:
    """Codec for Go UUIDs (BinaryMarshaler, gob type name "UUID").

    Compatible with github.com/google/uuid, github.com/satori/go.uuid,
    and github.com/gofrs/uuid — all encode UUIDs as 16 raw bytes via
    BinaryMarshaler.

    The gob type name is the unqualified Go type name, which is ``"UUID"``
    for all three libraries.
    """

    @staticmethod
    def decode(data: bytes) -> _uuid.UUID:
        """Decode 16 raw bytes to a uuid.UUID."""
        if len(data) != 16:
            raise ValueError(f"UUID binary payload must be 16 bytes, got {len(data)}")
        return _uuid.UUID(bytes=data)

    @staticmethod
    def encode(value: _uuid.UUID) -> bytes:
        """Encode a uuid.UUID to 16 raw bytes."""
        return value.bytes


# ---------------------------------------------------------------------------
# Default codec registry
# ---------------------------------------------------------------------------

DEFAULT_CODECS: dict[str, Codec] = {
    # time.Time implements GobEncoder → wire field 4
    "Time": Codec(decode=TimeCodec.decode, encode=TimeCodec.encode, marshaler_type="gob"),
    # uuid.UUID implements encoding.BinaryMarshaler only → wire field 5
    "UUID": Codec(decode=UUIDCodec.decode, encode=UUIDCodec.encode, marshaler_type="binary"),
}
"""All built-in codecs.  Pass to Decoder or Encoder to enable them all:

    dec = pygob.Decoder(f, codecs=pygob.DEFAULT_CODECS)
    enc = pygob.Encoder(buf, codecs=pygob.DEFAULT_CODECS)
"""


# ---------------------------------------------------------------------------
# time.Duration helpers  (Duration is int64 nanoseconds — no codec possible)
# ---------------------------------------------------------------------------

def duration_to_timedelta(ns: int) -> timedelta:
    """Convert a Go time.Duration (int64 nanoseconds) to datetime.timedelta.

    Note: Python timedelta has microsecond precision; sub-microsecond
    nanoseconds are truncated.

    Args:
        ns: Duration in nanoseconds as decoded from a gob int field.

    Returns:
        A datetime.timedelta representing the same duration.
    """
    return timedelta(microseconds=ns // 1000)


def timedelta_to_duration(td: timedelta) -> int:
    """Convert a datetime.timedelta to a Go time.Duration (int64 nanoseconds).

    Args:
        td: A datetime.timedelta.

    Returns:
        The duration in nanoseconds, suitable for encoding as a gob int.
    """
    return int(td.total_seconds() * 1_000_000_000)
