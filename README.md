# pygob

A pure-Python encoder and decoder for Go's [`encoding/gob`](https://pkg.go.dev/encoding/gob) binary serialization format. No dependencies beyond the standard library.

Any byte stream produced by Go's `encoding/gob` decodes correctly in Python. Any byte stream produced by pygob decodes correctly in Go.

## Table of Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Encoding: three ways to describe structs](#encoding-three-ways-to-describe-structs)
- [Scalar types](#scalar-types)
- [Collection types](#collection-types)
- [Stream-oriented API](#stream-oriented-api)
- [Interface values](#interface-values)
- [GobEncoder / BinaryMarshaler types](#gobencoder--binarymarshaler-types)
- [Named primitive types (SemanticType)](#named-primitive-types-semantictype)
- [Go–Python interchange examples](#gopython-interchange-examples)
- [Type mapping](#type-mapping)
- [Limitations](#limitations)
- [Exceptions](#exceptions)
- [Developer guide](#developer-guide)
- [Related projects](#related-projects)

## Installation

```bash
pip install pygob
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add pygob
```

## Quick start

### Decoding gob bytes from Go

```python
import pygob

# Bytes produced by Go's encoding/gob
with open("my_file.gob", "rb") as f:
    gob_bytes = f.read()
value = pygob.decode(gob_bytes)

# Scalars come back as native Python types
# Structs come back as GobStruct (dict-like with attribute access)
print(value.X, value["Y"])   # attribute or dict access
print(dict(value))            # {"X": 22, "Y": 33}
```

### Encoding Python values to gob

```python
import pygob
from pygob import Schema, GOB_INT, GOB_STRING, GOB_FLOAT, GOB_BOOL

PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)
gob_bytes = pygob.encode({"X": 22, "Y": 33}, schema=PointSchema)
```

### Round-trip

```python
import pygob
from pygob import Schema, GOB_INT

PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)
encoded = pygob.encode({"X": 10, "Y": 20}, schema=PointSchema)
decoded = pygob.decode(encoded)
assert decoded.X == 10
assert decoded.Y == 20
```

## Encoding: three ways to describe structs

### 1. Schema + plain dict

Provide a `Schema` object alongside the dict value. Good for one-off encoding without creating a class.

```python
from pygob import Schema, Encoder, GOB_INT, GOB_STRING, GOB_FLOAT, GOB_BOOL
import io

PersonSchema = Schema("Person", Name=GOB_STRING, Age=GOB_INT, Score=GOB_FLOAT, Active=GOB_BOOL)

buf = io.BytesIO()
enc = Encoder(buf)
enc.encode({"Name": "Alice", "Age": 30, "Score": 9.8, "Active": True}, schema=PersonSchema)
```

### 2. `@gobstruct` dataclass

Attach a gob schema to a dataclass. pygob inspects annotations and builds the schema automatically.

```python
from dataclasses import dataclass
from pygob import gobstruct, Encoder, UInt
import io

@gobstruct("Point")
@dataclass
class Point:
    X: int
    Y: int

@gobstruct("Person")
@dataclass
class Person:
    Name: str
    Age: int
    Location: Point    # nested struct — schema auto-derived

buf = io.BytesIO()
enc = Encoder(buf)
enc.encode(Point(X=22, Y=33))
enc.encode(Person(Name="Alice", Age=30, Location=Point(X=10, Y=20)))
```

### 3. GobStruct (decode → re-encode)

`GobStruct` instances carry their schema internally, so decoded values can be re-encoded without any additional setup.

```python
from pygob import Decoder, Encoder
import io

# Decode a Go-generated gob file
with open("struct_simple.gob", "rb") as f:
    decoded = Decoder(f).decode()  # returns GobStruct

# Re-encode with no extra configuration needed
buf = io.BytesIO()
Encoder(buf).encode(decoded)
```

## Scalar types

Scalars encode and decode as native Python types. Use `UInt` to force unsigned integer encoding.

```python
from pygob import encode, decode, UInt

encode(42)           # signed int
encode(UInt(42))     # unsigned int
encode(3.14)         # float64
encode(True)         # bool
encode("hello")      # string
encode(b"bytes")     # []byte
encode(1+2j)         # complex128
```

## Collection types

```python
from pygob import encode, decode, Schema, SliceOf, MapOf, ArrayOf, GOB_INT, GOB_STRING

# Slice (list)
encode([1, 2, 3])                              # type inferred as []int
encode(["a", "b", "c"])                        # type inferred as []string

# Map (dict)
encode({"one": 1, "two": 2})                   # type inferred as map[string]int

# Array (fixed-length)
encode([10, 20, 30], array_length=3)           # [3]int

# Slice of structs — provide elem_type
PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)
encode([{"X": 1, "Y": 2}, {"X": 3, "Y": 4}], elem_type=PointSchema)

# Map with struct values
encode({"origin": {"X": 0, "Y": 0}}, elem_type=PointSchema)

# Empty collections require explicit types
encode([], elem_type=GOB_INT)                  # []int{}
encode({}, key_type=GOB_STRING, elem_type=GOB_INT)   # map[string]int{}
```

### Collection descriptors in Schema

When a struct has collection fields, use `SliceOf`, `MapOf`, and `ArrayOf` in the schema:

```python
from pygob import Schema, SliceOf, MapOf, ArrayOf, GOB_INT, GOB_STRING, GOB_FLOAT

StatsSchema = Schema(
    "Stats",
    Scores=SliceOf(GOB_FLOAT),
    Labels=SliceOf(GOB_STRING),
    Lookup=MapOf(GOB_STRING, GOB_INT),
    Coords=ArrayOf(GOB_INT, 3),
)
```

The same descriptors work with `@gobstruct`:

```python
from dataclasses import dataclass
from pygob import gobstruct

@gobstruct("Point")
@dataclass
class Point:
    X: int
    Y: int

@gobstruct("Stats")
@dataclass
class Stats:
    Scores: list[float]
    Labels: list[str]
    Points: list[Point]            # slice of struct
    Lookup: dict[str, int]
```

## Stream-oriented API

For encoding or decoding multiple values to the same stream — as Go's `encoding/gob` is designed to do — use `Encoder` and `Decoder` directly:

```python
from pygob import Encoder, Decoder, Schema, GOB_INT
import io

PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)

# Encode multiple values; type definition emitted only once
buf = io.BytesIO()
enc = Encoder(buf)
enc.encode({"X": 1, "Y": 2}, schema=PointSchema)
enc.encode({"X": 3, "Y": 4}, schema=PointSchema)

# Decode multiple values from the same stream
buf.seek(0)
dec = Decoder(buf)
p1 = dec.decode()   # GobStruct(X=1, Y=2)
p2 = dec.decode()   # GobStruct(X=3, Y=4)
```

`decode()` raises `GobDecodeError` when the stream is exhausted. To read until end-of-stream, wrap in a try/except:

```python
from pygob import Decoder, GobDecodeError
import io

dec = Decoder(buf)
records = []
try:
    while True:
        records.append(dec.decode())
except GobDecodeError:
    pass  # stream exhausted
```

## Interface values

For **Go→Python decoding**, `register()` is not needed — the gob stream embeds inline type definitions that are fully self-describing:

```python
from pygob import Decoder

# No register() needed for Go-generated gob
with open("container.gob", "rb") as f:
    result = Decoder(f).decode()
print(result.Value.X)   # 10  — concrete type decoded automatically
```

For **Python→Go encoding**, register the concrete type so the encoder writes the correct Go type name into the interface field:

```python
from pygob import Encoder, Schema, GOB_INT, GOB_STRING
import io

PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)
ContainerSchema = Schema("Container", Name=GOB_STRING, Value=8)  # 8 = GOB_INTERFACE

buf = io.BytesIO()
enc = Encoder(buf)
enc.register("main.Point", PointSchema)   # register with fully-qualified Go name
enc.encode({"Name": "box", "Value": {"X": 10, "Y": 20}}, schema=ContainerSchema)
```

`@gobstruct`-decorated classes are auto-registered and do not need an explicit `register()` call:

```python
from dataclasses import dataclass
from pygob import gobstruct, Encoder, Schema, GOB_STRING, GOB_INTERFACE

@gobstruct("Point")   # auto-registered
@dataclass
class Point:
    X: int
    Y: int

ContainerSchema = Schema("Container", Name=GOB_STRING, Value=GOB_INTERFACE)
buf = io.BytesIO()
enc = Encoder(buf)
# No register() needed — Point was auto-registered by @gobstruct
enc.encode({"Name": "box", "Value": Point(X=10, Y=20)}, schema=ContainerSchema)
```

## GobEncoder / BinaryMarshaler types

Go types implementing `GobEncoder`, `BinaryMarshaler`, or `TextMarshaler` (e.g. `time.Time`, `uuid.UUID`) decode as `GobEncoded(type_name, raw_bytes)`. pygob ships built-in codecs for the most common types.

### Built-in codecs

```python
import pygob

# Enable all built-in codecs at construction time (recommended)
with open("data.gob", "rb") as f:
    dec = pygob.Decoder(f, codecs=pygob.DEFAULT_CODECS)
    t = dec.decode()   # time.Time → datetime.datetime, uuid.UUID → uuid.UUID

# Or with the convenience function
t = pygob.decode(data, codecs=pygob.DEFAULT_CODECS)
```

`DEFAULT_CODECS` includes:

| Go type | Python type | Gob type name |
|---------|------------|---------------|
| `time.Time` | `datetime.datetime` | `"Time"` |
| `uuid.UUID` (google/uuid) | `uuid.UUID` | `"UUID"` |

Encoding works symmetrically:

```python
from datetime import datetime, timezone
import io
import uuid
import pygob

buf = io.BytesIO()
enc = pygob.Encoder(buf, codecs=pygob.DEFAULT_CODECS)
enc.encode_gob_encoded(datetime(2009, 11, 10, 23, 0, 0, tzinfo=timezone.utc), "Time")
enc.encode_gob_encoded(uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8"), "UUID")
```

### Custom codecs

Register a custom decoder for any BinaryMarshaler/GobEncoder type:

```python
import pygob
from pygob import Decoder, Codec
from datetime import datetime

def decode_time(data: bytes) -> datetime:
    # parse Go binary time format
    ...

def encode_time(dt: datetime) -> bytes:
    ...

# Via constructor (preferred)
with open("scalar_time.gob", "rb") as f:
    dec = Decoder(f, codecs={"Time": Codec(decode=decode_time, encode=encode_time)})
    t = dec.decode()

# Or post-construction via register_codec
with open("scalar_time.gob", "rb") as f:
    dec = Decoder(f)
    dec.register_codec("Time", decode_time)
    t = dec.decode()
```

## Named primitive types (SemanticType)

Go supports named types over primitives — `type Duration int64`, `type Status string`, `type Celsius float64`. These encode as their underlying primitive on the wire, but the Python side may want a richer representation. Use `SemanticType` to define the mapping:

```python
import enum
from pygob import SemanticType, GOB_STRING, register_semantic_type, Schema, encode

class Status(enum.Enum):
    active = "active"
    inactive = "inactive"

GOB_STATUS = SemanticType(
    wire_type=GOB_STRING,
    python_type=Status,
    encode=lambda s: s.value,   # Status → str for the wire
    decode=Status,              # str → Status when decoding (future)
    zero=Status.active,
)

# Register so @gobstruct can infer it from annotations
register_semantic_type(Status, GOB_STATUS)

UserSchema = Schema("User", Name=GOB_STRING, Status=GOB_STATUS)
data = encode({"Name": "alice", "Status": Status.active}, schema=UserSchema)
```

With `register_semantic_type`, `@gobstruct` picks up the annotation automatically:

```python
from dataclasses import dataclass
from pygob import gobstruct

@gobstruct("User")
@dataclass
class User:
    Name: str
    Status: Status   # resolved to GOB_STATUS via register_semantic_type
```

`GOB_DURATION` is a built-in `SemanticType` — see below.

### time.Duration

Go's `time.Duration` is a plain `int64` (nanoseconds) on the wire — no BinaryMarshaler, no GobEncoder.

**Encoding** (Python→Go): use `GOB_DURATION` in a schema or `@gobstruct` annotation. pygob converts `timedelta` to nanoseconds automatically:

```python
from dataclasses import dataclass
from datetime import timedelta
from pygob import gobstruct, Schema, GOB_DURATION, GOB_STRING, encode

# With Schema + dict
EventSchema = Schema("Event", Name=GOB_STRING, Timeout=GOB_DURATION)
data = encode({"Name": "req", "Timeout": timedelta(seconds=5)}, schema=EventSchema)

# With @gobstruct
@gobstruct("Event")
@dataclass
class Event:
    Name: str
    Timeout: timedelta   # timedelta annotation → GOB_DURATION automatically

data = encode(Event(Name="req", Timeout=timedelta(seconds=5)))
```

**Decoding** (Go→Python): Duration fields arrive as plain `int` (nanoseconds). Use the conversion helpers:

```python
from pygob.codecs import duration_to_timedelta, timedelta_to_duration
from datetime import timedelta

td = duration_to_timedelta(5_000_000_000)        # 5s → timedelta(seconds=5)
ns = timedelta_to_duration(timedelta(minutes=1)) # → 60_000_000_000
```

## Go–Python interchange examples

These examples are validated by the project's cross-validation test suite (`tests/test_go_verify.py`), which encodes values in Python and decodes them with a live Go program.

### Go encodes, Python decodes

```go
// Go
type Point struct{ X, Y int }
var buf bytes.Buffer
enc := gob.NewEncoder(&buf)
enc.Encode(Point{22, 33})
```

```python
# Python
result = pygob.decode(buf_bytes)
assert result.X == 22
assert result.Y == 33
assert result.gob_type == "Point"
```

### Python encodes, Go decodes

```python
# Python
PointSchema = pygob.Schema("Point", X=pygob.GOB_INT, Y=pygob.GOB_INT)
data = pygob.encode({"X": 22, "Y": 33}, schema=PointSchema)
```

```go
// Go
type Point struct{ X, Y int }
var p Point
gob.NewDecoder(bytes.NewReader(data)).Decode(&p)
// p == Point{22, 33}
```

### Nested structs

```python
@gobstruct("Point")
@dataclass
class Point:
    X: int
    Y: int

@gobstruct("NestedStruct")
@dataclass
class NestedStruct:
    Label: str
    Origin: Point

data = pygob.encode(NestedStruct(Label="origin", Origin=Point(X=0, Y=0)))
```

```go
type NestedStruct struct {
    Label  string
    Origin Point
}
var ns NestedStruct
gob.NewDecoder(bytes.NewReader(data)).Decode(&ns)
```

## Type mapping

| Go type | Python type (decoded) | Python type (encoded) |
|---|---|---|
| `int` | `int` | `int` |
| `uint` | `int` | `UInt(n)` |
| `bool` | `bool` | `bool` |
| `float64` | `float` | `float` |
| `complex128` | `complex` | `complex` |
| `string` | `str` | `str` |
| `[]byte` | `bytes` | `bytes` |
| `[]T` | `list` | `list` (with `elem_type` or schema) |
| `[N]T` | `list` | `list` (with `array_length`) |
| `map[K]V` | `dict` | `dict` (with `key_type`/`elem_type` or schema) |
| `struct` | `GobStruct` | `dict+Schema`, `GobStruct`, or `@gobstruct` dataclass |
| `interface{}` | inner value | registered concrete type (see [Interface values](#interface-values)) |
| `GobEncoder` / `BinaryMarshaler` / `TextMarshaler` | `GobEncoded(name, bytes)` or custom type if codec registered | `encode_gob_encoded()` |
| `time.Time` (with `DEFAULT_CODECS`) | `datetime.datetime` | `encode_gob_encoded(dt, "Time")` |
| `uuid.UUID` (with `DEFAULT_CODECS`) | `uuid.UUID` | `encode_gob_encoded(u, "UUID")` |
| `time.Duration` | `int` (nanoseconds) | `timedelta` with `GOB_DURATION` in schema |
| any named primitive (e.g. `type Status string`) | underlying primitive | custom Python type with `SemanticType` |

## Limitations

- **`interface{}` encoding requires type registration.** For Go→Python decoding, `register()` is not needed — the gob stream embeds inline type definitions that are fully self-describing. However, for Python→Python or Python→Go encoding of interface fields, call `encoder.register(go_name, schema)` so the encoder knows the concrete type's schema. `@gobstruct`-decorated classes are auto-registered and do not require an explicit `register()` call.
- **No pointer types.** Go pointers are transparent in gob (a `*Point` encodes identically to `Point`). pygob does not model pointers.
- **No channel, function, or unexported fields.** Go's `encoding/gob` itself rejects these; pygob follows suit.
- **Array length not preserved on decoded values.** Go `[3]int` decodes to a Python `list` of 3 elements; the fixed-length annotation is lost (but re-encoding with the correct schema restores it).
- **Map ordering.** Go map iteration order is random, so byte-level comparison of map-containing gob streams is not reliable. Decode and compare values instead.
- **Arbitrary-precision integers.** Python `int` is unbounded; gob is bounded to 64-bit integers. Values exceeding 64 bits will decode correctly in Python but will not be accepted by a standard Go decoder.
- **`time.Duration` decodes as `int`.** Go `time.Duration` is a plain `int64` (nanoseconds) on the wire — no BinaryMarshaler, no GobEncoder. When decoding Go-generated gob without a schema, Duration fields arrive as Python `int`. Use `pygob.codecs.duration_to_timedelta()` to convert. For encoding, annotate the schema field with `GOB_DURATION` (or use a `timedelta` annotation in a `@gobstruct` dataclass) and pygob handles the conversion automatically.
- **Schema evolution.** Adding or removing struct fields is safe: unknown fields from Go are silently ignored; missing fields are filled with zero values. This is a gob protocol guarantee that pygob inherits automatically.

## Exceptions

```python
from pygob import GobError, GobDecodeError, GobEncodeError

try:
    pygob.decode(bad_bytes)
except GobDecodeError as e:
    print("decode failed:", e)
```

**Exception hierarchy:**

```
GobError (base)
├── GobDecodeError   (truncated stream, unknown type ID, malformed data, end of stream)
└── GobEncodeError   (unsupported type, missing required fields, schema error)
```

| Exception | When raised |
|---|---|
| `GobDecodeError` | Truncated stream, unknown type ID, malformed data, end of stream |
| `GobEncodeError` | Type mismatch, missing required fields |

---

## Developer guide

### Project layout

```
pygob/
├── __init__.py      # Public API
├── codec.py         # Unsigned/signed int, float, string, bytes encode/decode
├── wire.py          # Bootstrap type IDs, wireType struct definitions and decoding
├── types.py         # GobStruct, Schema, @gobstruct, UInt, SemanticType, SliceOf, MapOf, ArrayOf
├── decoder.py       # Decoder: stream framing, type registry, value decoding
└── encoder.py       # Encoder: stream framing, type emission, value encoding

tests/
├── generate_testdata.go   # Go program: generates .gob + .json testdata pairs
├── go_verify/
│   └── main.go            # Go program: reads gob from stdin, returns JSON result
├── testdata/              # Generated fixtures (.gob + .json pairs, committed)
├── conftest.py            # Fixtures: testdata loader, go_verify subprocess helper
├── test_codec.py          # Low-level encode/decode (uint, int, float, …)
├── test_decoder.py        # Full message decoding against Go-generated .gob files
├── test_encoder.py        # Encoding + Python round-trip tests
├── test_go_verify.py      # Cross-validation: Python encodes → Go decodes
└── test_types.py          # GobStruct, Schema, @gobstruct, SliceOf/MapOf/ArrayOf
```

### Running tests

```bash
uv run pytest                           # all tests
uv run pytest tests/test_codec.py       # one file
uv run pytest -x                        # stop on first failure
uv run pytest tests/test_go_verify.py   # Go cross-validation (requires go on PATH)
```

### Regenerating test fixtures

```bash
go run tests/generate_testdata.go
```

This writes `.gob` and `.json` sidecar files to `tests/testdata/`. Commit both — the `.gob` files are the ground truth for decoder tests, and the `.json` files describe expected decoded values.

To manually test the Go verifier:

```bash
cat tests/testdata/struct_simple.gob | go run ./tests/go_verify struct_simple
# {"ok":true,"value":{"X":22,"Y":33}}
```

### Three layers of validation

1. **Go → Python (decoder tests):** `tests/test_decoder.py` decodes Go-generated `.gob` files and asserts against the `.json` sidecars. Catches bugs in the Python decoder.

2. **Python → Python (round-trip tests):** `tests/test_encoder.py` encodes a Python value, decodes it back, and asserts values match. Catches asymmetric encoder/decoder bugs — but not symmetric ones.

3. **Python → Go (cross-validation tests):** `tests/test_go_verify.py` encodes a Python value and pipes the bytes to `go run ./tests/go_verify`. This is the authoritative proof that Python produces Go-compatible output. Tests are skipped (not failed) when Go is not on `PATH`, so they never break CI in Go-free environments.

### Why byte-level comparison is limited to scalars and struct_simple

Go's `encoding/gob` maintains a **global** type registry within a process. Type IDs accumulate across encoder instances: if `generate_testdata.go` registers `Point` first, then `MixedStruct`, then `NestedStruct`, they get IDs 64, 65, 66 in that process — starting from 64, one below `firstUserId = 65` in Go's source, due to a pre-decrement in the allocator.

Python's `Encoder` always starts fresh at `FIRST_USER_ID = 65`, matching Go's stated constant. A standalone Python encode of any struct always assigns it ID 65, which will differ from Go's accumulated IDs for any type other than the very first one registered in a Go process.

Consequence: byte-level comparison against Go-generated `.gob` files is reliable for:
- All scalars (no user type IDs involved)

For all other struct types, maps, slices of structs, and nested types, use the `go_verify` cross-validation tests. They pipe Python-encoded bytes into a live Go decoder and are completely unaffected by type ID values.

### Cross-language design intent

pygob's type descriptor model — `SliceOf`, `MapOf`, `ArrayOf`, `GOB_INT`, `GOB_STRING`, etc. — is designed to map cleanly to generic types in statically-typed languages. The goal is that sister libraries in C# and TypeScript use the same names and concepts:

| Concept | Python | TypeScript | C# |
|---|---|---|---|
| Slice descriptor | `SliceOf(GOB_INT)` | `SliceOf<GobType>` | `SliceOf<int>` |
| Map descriptor | `MapOf(GOB_STRING, GOB_INT)` | `MapOf<K, V>` | `MapOf<TKey, TValue>` |
| Unsigned int | `UInt(n)` (subclasses `int`) | branded `UInt` number | native `uint` |
| Schema | `Schema("Point", X=GOB_INT)` | `Schema` class | `Schema` class |

The mental model transfers directly across languages: the concept is the same, the idiom is language-native.

## Related projects

- [gobdotnet](https://github.com/codepuke/gobdotnet) — C# port, shares testdata and the same mental model.
- [encoding/gob](https://pkg.go.dev/encoding/gob) — Go's standard library implementation, the authoritative wire format specification.
