---
title: Decoding Values
---

# Decoding Values

## What comes back

Decoding produces plain Python types. There is no wrapper class to unwrap and no
schema to supply — a gob stream carries its own type definitions inline, so it is
fully self-describing.

```python
import pygob

with open("my_file.gob", "rb") as f:
    value = pygob.decode(f.read())
```

Scalars decode to `int`, `float`, `bool`, `str`, `bytes`, and `complex`; slices
and arrays to `list`; maps to `dict`. The one rich type is `GobStruct`.

## `GobStruct`

A decoded struct is a `GobStruct`: a dict-like object that supports both item and
attribute access, and additionally knows its Go type name.

:::examples decode-struct

`GobStruct` supports the dict protocol — `len()`, `in`, iteration, `.keys()`,
`.values()`, `.items()`, `.get()`, `dict(...)` conversion, and `==` against
either another `GobStruct` or a plain dict. It also carries `.gob_schema`, the
full field schema, which is what allows a decoded value to be re-encoded without
any additional configuration.

## Signedness

Go `int` and Go `uint` both decode to a plain Python `int`. The distinction is
tracked in the type registry during decoding, not carried on the value — Python
has one integer type, and inventing a second one for decoded values would make
every downstream comparison and arithmetic operation surprising. When
re-encoding, use `UInt` to restore the unsigned encoding.

## Errors

`decode()` raises `GobDecodeError` for a truncated stream, an unknown type id,
malformed data, or a read past end-of-stream.

```python
import pygob
from pygob import GobDecodeError

try:
    pygob.decode(bad_bytes)
except GobDecodeError as e:
    print("decode failed:", e)
```

End-of-stream raising rather than returning a sentinel is what makes the
[read-until-exhausted loop](streams) work.
