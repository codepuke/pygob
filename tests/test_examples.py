"""Executable documentation examples.

Every region delimited by the snippet start/end comment markers below is
extracted by the codepuke site (see ``SYNCING.md`` in that repo) and rendered
alongside the Go, TypeScript, and C# variants of the same topic. Because the
regions live in a pytest file, a snippet that stops working fails the suite.

Rules that matter when editing this file:

*   A topic id appears at most once per file, and at most once per language
    across all sibling repos. Coordinate ids via ``content/manifest.json``.
*   Marker lines are stripped and the region is dedented, so a region inside a
    test body extracts as clean top-level code. Keep fixtures, plumbing, and
    assertions *outside* the markers.
*   Each variant of a topic should do the same thing with the same data, so
    the tabs line up. ``Point{X: 3, Y: 4}`` is the shared running example.
"""

from __future__ import annotations

import enum
import io
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pygob
from pygob import (
    DEFAULT_CODECS,
    GOB_INT,
    GOB_INTERFACE,
    GOB_STRING,
    Decoder,
    Encoder,
    GobDecodeError,
    GobStruct,
    Schema,
    SemanticType,
    UInt,
    gobstruct,
)


# ---------------------------------------------------------------------------
# Structs
# ---------------------------------------------------------------------------


def test_encode_struct():
    """Encode a plain dict as a Go struct by pairing it with a Schema."""
    # snippet:start encode-struct
    PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)
    data = pygob.encode({"X": 3, "Y": 4}, schema=PointSchema)
    # snippet:end

    assert isinstance(data, bytes)
    assert pygob.decode(data) == {"X": 3, "Y": 4}


def test_decode_struct():
    """A decoded struct is a GobStruct: dict access, attribute access, type name."""
    schema = Schema("Point", X=GOB_INT, Y=GOB_INT)
    data = pygob.encode({"X": 3, "Y": 4}, schema=schema)

    # snippet:start decode-struct
    point = pygob.decode(data)

    print(point.X)           # 3    — attribute access
    print(point["Y"])        # 4    — item access
    print(point.gob_type)    # "Point" — the Go type name
    print(dict(point))       # {"X": 3, "Y": 4}
    # snippet:end

    assert isinstance(point, GobStruct)
    assert point.X == 3
    assert point["Y"] == 4
    assert point.gob_type == "Point"
    assert dict(point) == {"X": 3, "Y": 4}


def test_round_trip():
    """Encode a value and decode it back."""
    # snippet:start round-trip
    PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)

    data = pygob.encode({"X": 3, "Y": 4}, schema=PointSchema)
    point = pygob.decode(data)

    assert point.X == 3
    assert point.Y == 4
    # snippet:end


def test_schema_type_inference():
    """@gobstruct derives the schema from a dataclass's type annotations."""
    # snippet:start schema-type-inference
    @gobstruct("Person")
    @dataclass
    class Person:
        Name: str   # inferred → GOB_STRING
        Age: int    # inferred → GOB_INT

    data = pygob.encode(Person(Name="Ada", Age=36))
    # snippet:end

    decoded = pygob.decode(data)
    assert decoded.gob_type == "Person"
    assert (decoded.Name, decoded.Age) == ("Ada", 36)


def test_nested_struct():
    """A struct field may itself be a struct: pass the inner Schema as the field type."""
    # snippet:start nested-struct
    # Go: type Line struct { From, To Point }
    PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)

    # A Schema is itself a field type, so it nests directly.
    LineSchema = Schema("Line", From=PointSchema, To=PointSchema)

    data = pygob.encode(
        {"From": {"X": 1, "Y": 2}, "To": {"X": 3, "Y": 4}},
        schema=LineSchema,
    )

    line = pygob.decode(data)
    print(line.To.X)   # 3
    # snippet:end

    assert line.From.X == 1
    assert line.From.Y == 2
    assert line.To.X == 3
    assert line.To.Y == 4


def test_zero_fields_omitted():
    """Zero-valued fields never reach the wire, but decode back as zero."""
    # snippet:start zero-fields-omitted
    PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)

    full = pygob.encode({"X": 3, "Y": 4}, schema=PointSchema)
    partial = pygob.encode({"X": 3, "Y": 0}, schema=PointSchema)

    # Y == 0 is simply absent from the encoded bytes...
    assert len(partial) < len(full)

    # ...but the decoder still fills it in.
    assert pygob.decode(partial).Y == 0
    # snippet:end


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------


def test_encode_scalars():
    """Scalars encode from native Python types. UInt forces unsigned encoding."""
    # snippet:start encode-scalars
    pygob.encode(42)             # int      → signed int
    pygob.encode(UInt(42))       # UInt     → unsigned int
    pygob.encode(3.14159)        # float    → float64
    pygob.encode(True)           # bool     → bool
    pygob.encode("hello, 世界")   # str      → string
    pygob.encode(b"raw")         # bytes    → []byte
    pygob.encode(1 + 2j)         # complex  → complex128
    # snippet:end

    assert pygob.decode(pygob.encode(42)) == 42
    assert pygob.decode(pygob.encode(UInt(42))) == 42
    assert pygob.decode(pygob.encode("hello, 世界")) == "hello, 世界"
    assert pygob.decode(pygob.encode(b"raw")) == b"raw"
    assert pygob.decode(pygob.encode(1 + 2j)) == 1 + 2j


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


def test_encode_slice():
    """A list encodes as a slice; the element type is inferred from the values."""
    # snippet:start encode-slice
    data = pygob.encode([1, 2, 3])          # []int
    # snippet:end

    assert pygob.decode(data) == [1, 2, 3]
    assert pygob.decode(pygob.encode(["a", "b"])) == ["a", "b"]


def test_encode_map():
    """A dict encodes as a map; key and element types are inferred."""
    # snippet:start encode-map
    data = pygob.encode({"one": 1, "two": 2})   # map[string]int
    # snippet:end

    assert pygob.decode(data) == {"one": 1, "two": 2}


def test_encode_array():
    """array_length encodes a list as a fixed-size array rather than a slice."""
    # snippet:start encode-array
    data = pygob.encode([1, 2, 3], array_length=3)   # [3]int
    # snippet:end

    assert pygob.decode(data) == [1, 2, 3]


def test_empty_collections():
    """Empty collections carry no values to infer from, so state the types."""
    # snippet:start empty-collections
    empty_slice = pygob.encode([], elem_type=GOB_INT)                    # []int{}
    empty_map = pygob.encode({}, key_type=GOB_STRING, elem_type=GOB_INT)  # map[string]int{}
    # snippet:end

    assert pygob.decode(empty_slice) == []
    assert pygob.decode(empty_map) == {}


def test_slice_of_structs():
    """A slice of structs needs elem_type, since a dict alone is ambiguous."""
    # snippet:start slice-of-structs
    PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)

    data = pygob.encode(
        [{"X": 3, "Y": 4}, {"X": 5, "Y": 6}],
        elem_type=PointSchema,
    )
    # snippet:end

    points = pygob.decode(data)
    assert [p.X for p in points] == [3, 5]
    assert [p.Y for p in points] == [4, 6]


# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------


def test_stream_multiple_values():
    """One Encoder over one stream: the type definition is emitted only once."""
    # snippet:start stream-multiple-values
    PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)

    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"X": 3, "Y": 4}, schema=PointSchema)
    enc.encode({"X": 5, "Y": 6}, schema=PointSchema)

    buf.seek(0)
    dec = Decoder(buf)
    first = dec.decode()
    second = dec.decode()
    # snippet:end

    assert (first.X, first.Y) == (3, 4)
    assert (second.X, second.Y) == (5, 6)

    # The second value is far smaller: it reuses the first message's type id.
    standalone = pygob.encode({"X": 5, "Y": 6}, schema=PointSchema)
    assert len(buf.getvalue()) < 2 * len(standalone)


def test_end_of_stream():
    """decode() raises GobDecodeError once the stream is exhausted."""
    schema = Schema("Point", X=GOB_INT, Y=GOB_INT)
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.encode({"X": 3, "Y": 4}, schema=schema)
    enc.encode({"X": 5, "Y": 6}, schema=schema)
    buf.seek(0)

    # snippet:start end-of-stream
    dec = Decoder(buf)
    records = []
    try:
        while True:
            records.append(dec.decode())
    except GobDecodeError:
        pass    # stream exhausted
    # snippet:end

    assert len(records) == 2
    assert [r.X for r in records] == [3, 5]


# ---------------------------------------------------------------------------
# Interface values
# ---------------------------------------------------------------------------


def test_interface_values():
    """Encoding into an interface field needs the concrete type's Go name."""
    # snippet:start interface-values
    # Go: type Box struct { Value any }
    PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)
    BoxSchema = Schema("Box", Value=GOB_INTERFACE)

    # An interface value travels with its concrete type name, which Go
    # qualifies by package — "main.Point", not "Point". Register that name;
    # it must match whatever the Go side passed to gob.Register.
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.register("main.Point", PointSchema)

    point = GobStruct("Point", PointSchema, X=3, Y=4)
    enc.encode({"Value": point}, schema=BoxSchema)

    buf.seek(0)
    box = Decoder(buf).decode()
    print(box.Value.X)   # 3
    # snippet:end

    assert box.Value.X == 3
    assert box.Value.Y == 4


# ---------------------------------------------------------------------------
# Codecs and named types
# ---------------------------------------------------------------------------


def test_time_values():
    """Go's time.Time maps to datetime via the built-in Time codec."""
    # snippet:start time-values
    # Go's time.Time implements GobEncoder (not BinaryMarshaler) and arrives
    # on the wire under the unqualified type name "Time".
    buf = io.BytesIO()
    enc = Encoder(buf, codecs=DEFAULT_CODECS)
    enc.encode_gob_encoded(datetime(2009, 11, 10, 23, 0, tzinfo=timezone.utc), "Time")

    when = pygob.decode(buf.getvalue(), codecs=DEFAULT_CODECS)
    print(when.isoformat())   # 2009-11-10T23:00:00+00:00

    # Python's datetime holds microseconds; Go holds nanoseconds. Go values
    # with sub-microsecond precision lose it in the conversion.
    # snippet:end

    assert when == datetime(2009, 11, 10, 23, 0, tzinfo=timezone.utc)
    assert when.isoformat() == "2009-11-10T23:00:00+00:00"


def test_uuid_values():
    """A Go uuid.UUID maps to Python's uuid.UUID via the built-in codec."""
    # snippet:start uuid-values
    # uuid.UUID is a BinaryMarshaler, wire type name "UUID".
    buf = io.BytesIO()
    enc = Encoder(buf, codecs=DEFAULT_CODECS)
    enc.encode_gob_encoded(uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8"), "UUID")

    ident = pygob.decode(buf.getvalue(), codecs=DEFAULT_CODECS)
    print(ident)   # 6ba7b810-9dad-11d1-80b4-00c04fd430c8
    # snippet:end

    assert ident == uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def test_custom_marshaler():
    """Any marshaler type can be bridged with a pair of byte-level functions."""
    # snippet:start custom-marshaler
    # Go: type Celsius float64, with MarshalBinary / UnmarshalBinary writing
    # eight big-endian IEEE-754 bytes.
    def encode_celsius(value: float) -> bytes:
        return struct.pack(">d", value)

    def decode_celsius(data: bytes) -> float:
        return struct.unpack(">d", data)[0]

    # Register under the unqualified Go type name, on both sides.
    buf = io.BytesIO()
    enc = Encoder(buf)
    enc.register_codec("Celsius", encode_celsius, marshaler_type="binary")
    enc.encode_gob_encoded(21.5, "Celsius")

    buf.seek(0)
    dec = Decoder(buf)
    dec.register_codec("Celsius", decode_celsius)
    temperature = dec.decode()   # 21.5
    # snippet:end

    assert temperature == 21.5


def test_semantic_type():
    """A named Go primitive maps onto a richer Python type with SemanticType."""
    # snippet:start semantic-type
    # Go: type Status string
    class Status(enum.Enum):
        ACTIVE = "active"
        INACTIVE = "inactive"

    GOB_STATUS = SemanticType(
        wire_type=GOB_STRING,
        encode=lambda status: status.value,   # Status → str for the wire
        decode=Status,                        # str → Status
        zero=Status.INACTIVE,
    )

    UserSchema = Schema("User", Name=GOB_STRING, Status=GOB_STATUS)

    data = pygob.encode({"Name": "Ada", "Status": Status.ACTIVE}, schema=UserSchema)

    # Nothing on the wire marks the field as a Status, so without a schema it
    # decodes back as the underlying primitive.
    user = pygob.decode(data)
    print(user.Status)   # "active"
    # snippet:end

    assert user.Name == "Ada"
    assert user.Status == "active"


# ---------------------------------------------------------------------------
# Guard: the snippet markers themselves stay well-formed
# ---------------------------------------------------------------------------


def test_snippet_markers_are_well_formed():
    """Every snippet:start has a matching end, and no topic id is reused.

    The codepuke sync fails loudly on malformed markers, and it runs in the
    codepuke repo, long after a bad edit lands here. This check fails first.
    """
    import ast
    import re
    from pathlib import Path

    source = Path(__file__).read_text(encoding="utf-8")
    source_lines = source.splitlines()

    # Scan only the example region: below the module docstring, above this
    # guard. Both of those mention the marker syntax without using it.
    module = ast.parse(source)
    start = 0
    if module.body and isinstance(module.body[0], ast.Expr) and isinstance(
        module.body[0].value, ast.Constant
    ):
        start = module.body[0].end_lineno
    end = test_snippet_markers_are_well_formed.__code__.co_firstlineno - 1
    topic_re = re.compile(r"^[a-z0-9][a-z0-9-]*$")

    open_stack: list[str] = []
    seen: set[str] = set()
    for lineno, line in enumerate(source_lines[start:end], start=start + 1):
        stripped = line.strip()
        if not stripped.startswith("# snippet:"):
            # The marker must be the only thing on its line.
            assert "# snippet:" not in line, f"line {lineno}: marker not alone on its line"
            continue
        parts = stripped.removeprefix("# snippet:").split()
        verb = parts[0]
        if verb == "start":
            assert len(parts) == 2, f"line {lineno}: snippet:start needs exactly one topic"
            topic = parts[1]
            assert topic_re.match(topic), f"line {lineno}: bad topic id {topic!r}"
            assert topic not in seen, f"line {lineno}: topic {topic!r} used twice in this file"
            seen.add(topic)
            open_stack.append(topic)
        elif verb == "end":
            assert open_stack, f"line {lineno}: snippet:end with no open region"
            opened = open_stack.pop()
            if len(parts) == 2:
                assert parts[1] == opened, f"line {lineno}: end {parts[1]!r} closes {opened!r}"
        else:
            raise AssertionError(f"line {lineno}: unknown snippet verb {verb!r}")

    assert not open_stack, f"unclosed snippet regions: {open_stack}"
    assert seen, "no snippet regions found"
