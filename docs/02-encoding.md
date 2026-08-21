---
title: Encoding Values
---

# Encoding Values

## Scalars

Scalars encode from native Python types. `UInt` is the only wrapper type pygob
defines, and it exists for one reason: Python's `int` cannot say whether a value
is meant to be a Go `int` or a Go `uint`.

:::examples encode-scalars

`UInt` subclasses `int`, so it behaves like an `int` everywhere else — arithmetic,
comparison, and use as a dict key all work unchanged.

## Three ways to describe a struct

Go structs are typed on the wire, so the encoder needs to know the type name and
the field types. pygob offers three ways to supply that, all producing identical
bytes.

### 1. Schema + plain dict

Best for one-off encoding without defining a class.

:::examples encode-struct

A `Schema` is just a name plus ordered field types. Field order matters: it
determines the field numbers used on the wire.

```python
from pygob import Schema, GOB_STRING, GOB_INT, GOB_FLOAT, GOB_BOOL

PersonSchema = Schema(
    "Person",
    Name=GOB_STRING,
    Age=GOB_INT,
    Score=GOB_FLOAT,
    Active=GOB_BOOL,
)
```

### 2. `@gobstruct` dataclass

Attach a gob type name to a dataclass and pygob derives the schema from the type
annotations.

:::examples schema-type-inference

Nested struct annotations resolve automatically, so a field annotated with
another `@gobstruct` class needs no extra configuration:

```python
from dataclasses import dataclass
from pygob import gobstruct

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
```

`@gobstruct` classes are also auto-registered for [interface encoding](interfaces).

### 3. Re-encoding a decoded `GobStruct`

A `GobStruct` carries its schema internally, so a value decoded from a Go-produced
stream can be re-encoded with no additional setup:

```python
from pygob import Decoder, Encoder
import io

with open("struct_simple.gob", "rb") as f:
    decoded = Decoder(f).decode()   # GobStruct

buf = io.BytesIO()
Encoder(buf).encode(decoded)        # no schema argument needed
```

## Zero-valued fields are omitted

Gob transmits struct fields as delta-encoded (field number, value) pairs, and
skips any field holding its type's zero value. This is a wire-format property,
not a pygob optimisation — the decoder fills the field back in.

:::examples zero-fields-omitted

The practical consequence is that a struct where every field is zero encodes to
just its type definition and a terminator. It also means byte-length is not a
reliable proxy for "did my data get encoded".
