---
title: Interface Values
---

# Interface Values

A Go `interface{}` field transmits the concrete type's name alongside the value.
The two directions have different requirements.

## Go → Python: nothing to configure

Decoding needs no registration. The stream embeds the concrete type's definition
inline, so the decoder resolves it on the fly and returns the inner value —
a `GobStruct` with `.gob_type` set, when the concrete value is a struct.

```python
from pygob import Decoder

with open("container.gob", "rb") as f:
    result = Decoder(f).decode()

print(result.Value.X)   # 10 — concrete type decoded automatically
```

## Python → Go: register the concrete type

Encoding is the direction that needs help, because pygob has to write a Go type
name it cannot otherwise know. Register it against the concrete type's schema,
using the fully-qualified Go name (`main.Point`, not `Point`).

:::examples interface-value

Use `GOB_INTERFACE` as the field type in the containing schema.

## `@gobstruct` classes register themselves

A class decorated with `@gobstruct` is added to the registry at decoration time,
so no explicit `register()` call is needed:

```python
from dataclasses import dataclass
from pygob import gobstruct, Encoder, Schema, GOB_STRING, GOB_INTERFACE
import io

@gobstruct("Point")   # auto-registered
@dataclass
class Point:
    X: int
    Y: int

ContainerSchema = Schema("Container", Name=GOB_STRING, Value=GOB_INTERFACE)

buf = io.BytesIO()
enc = Encoder(buf)
enc.encode({"Name": "box", "Value": Point(X=10, Y=20)}, schema=ContainerSchema)
```

Encoding an interface field holding a struct with no registration and no
`@gobstruct` decoration raises `GobEncodeError`.
