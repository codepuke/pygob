---
title: Custom & Named Types
---

# Custom & Named Types

Go has two ways to put a type on the wire that is not one of gob's built-ins:
implement a marshaler interface, or define a named type over a primitive. pygob
handles each differently, because they look different on the wire.

## `GobEncoder` / `BinaryMarshaler` / `TextMarshaler`

Types implementing one of these interfaces — `time.Time` and `uuid.UUID` being
the common ones — appear on the wire as an opaque byte blob tagged with a type
name. Without a codec, pygob decodes them to `GobEncoded(type_name, data)`,
which preserves the bytes exactly so the value can be re-encoded untouched.

### Built-in codecs

`DEFAULT_CODECS` turns the two most common types into their Python equivalents:

| Go type | Python type | Gob type name |
|---------|-------------|---------------|
| `time.Time` | `datetime.datetime` | `"Time"` |
| `uuid.UUID` (google/uuid) | `uuid.UUID` | `"UUID"` |

```python
import pygob

with open("data.gob", "rb") as f:
    dec = pygob.Decoder(f, codecs=pygob.DEFAULT_CODECS)
    t = dec.decode()   # datetime.datetime, not GobEncoded

# Or with the one-shot function
t = pygob.decode(data, codecs=pygob.DEFAULT_CODECS)
```

Encoding is symmetric, but the type name must be given explicitly, since one
Python type could correspond to several Go marshaler types:

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

The full round trip for each built-in codec:

:::examples time-values

:::examples uuid-values

### Custom codecs

Any marshaler type can be given a codec. Pass them at construction, or register
a decoder after the fact:

```python
import pygob
from pygob import Decoder, Codec
from datetime import datetime

def decode_time(data: bytes) -> datetime:
    ...   # parse Go's binary time format

def encode_time(dt: datetime) -> bytes:
    ...

# Via constructor (preferred — applies to every value on the stream)
with open("scalar_time.gob", "rb") as f:
    dec = Decoder(f, codecs={"Time": Codec(decode=decode_time, encode=encode_time)})
    t = dec.decode()

# Or post-construction, decode side only
with open("scalar_time.gob", "rb") as f:
    dec = Decoder(f)
    dec.register_codec("Time", decode_time)
    t = dec.decode()
```

A complete both-sides example, bridging a Go `type Celsius float64` whose
marshaler writes eight big-endian IEEE-754 bytes:

:::examples custom-marshaler

## Named primitive types

Go's `type Status string`, `type Celsius float64`, and `type Duration int64`
encode as their underlying primitive — there is no marshaler involved and nothing
on the wire distinguishes them. `SemanticType` describes the mapping between such
a primitive and a richer Python type.

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
    decode=Status,              # str → Status
    zero=Status.active,
)

register_semantic_type(Status, GOB_STATUS)

UserSchema = Schema("User", Name=GOB_STRING, Status=GOB_STATUS)
data = encode({"Name": "alice", "Status": Status.active}, schema=UserSchema)
```

:::examples semantic-type

`register_semantic_type` is what lets `@gobstruct` resolve the annotation:

```python
from dataclasses import dataclass
from pygob import gobstruct

@gobstruct("User")
@dataclass
class User:
    Name: str
    Status: Status   # resolved to GOB_STATUS via register_semantic_type
```

## `time.Duration`

`time.Duration` is the named-primitive case that comes up most: a plain `int64`
of nanoseconds, with no marshaler. pygob ships `GOB_DURATION` as a built-in
`SemanticType` mapping it to `datetime.timedelta`.

Encoding — use `GOB_DURATION` in a schema, or annotate a `@gobstruct` field with
`timedelta`:

```python
from dataclasses import dataclass
from datetime import timedelta
from pygob import gobstruct, Schema, GOB_DURATION, GOB_STRING, encode

EventSchema = Schema("Event", Name=GOB_STRING, Timeout=GOB_DURATION)
data = encode({"Name": "req", "Timeout": timedelta(seconds=5)}, schema=EventSchema)

@gobstruct("Event")
@dataclass
class Event:
    Name: str
    Timeout: timedelta   # timedelta annotation → GOB_DURATION automatically

data = encode(Event(Name="req", Timeout=timedelta(seconds=5)))
```

Decoding — because nothing on the wire marks the field as a Duration, it arrives
as a plain `int` of nanoseconds when decoding Go-generated gob without a schema.
Convert explicitly:

```python
from datetime import timedelta
from pygob.codecs import duration_to_timedelta, timedelta_to_duration

td = duration_to_timedelta(5_000_000_000)         # → timedelta(seconds=5)
ns = timedelta_to_duration(timedelta(minutes=1))  # → 60_000_000_000
```
