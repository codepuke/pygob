---
title: Type Mapping & Limitations
---

# Type Mapping & Limitations

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
| `struct` | `GobStruct` | `dict` + `Schema`, `GobStruct`, or `@gobstruct` dataclass |
| `interface{}` | inner value | registered concrete type — see [Interface Values](interfaces) |
| `GobEncoder` / `BinaryMarshaler` / `TextMarshaler` | `GobEncoded(name, bytes)`, or a custom type with a codec | `encode_gob_encoded()` |
| `time.Time` (with `DEFAULT_CODECS`) | `datetime.datetime` | `encode_gob_encoded(dt, "Time")` |
| `uuid.UUID` (with `DEFAULT_CODECS`) | `uuid.UUID` | `encode_gob_encoded(u, "UUID")` |
| `time.Duration` | `int` (nanoseconds) | `timedelta` with `GOB_DURATION` in the schema |
| named primitive (e.g. `type Status string`) | underlying primitive | custom Python type via `SemanticType` |

## Limitations

- **`interface{}` encoding requires type registration.** Decoding does not —
  the stream is self-describing. Encoding an interface field needs
  `encoder.register(go_name, schema)`, or a `@gobstruct` class, which registers
  itself.
- **No pointer types.** Go pointers are transparent in gob (`*Point` encodes
  identically to `Point`), so pygob does not model them.
- **No channel, function, or unexported fields.** Go's `encoding/gob` rejects
  these itself; pygob follows suit.
- **Array length is not preserved on decoded values.** Go `[3]int` decodes to a
  3-element `list`; re-encoding with the right schema restores the annotation.
- **Map ordering is not stable.** Go map iteration order is random, so
  byte-level comparison of map-containing streams is meaningless. Compare
  decoded values.
- **Arbitrary-precision integers.** Python's `int` is unbounded; gob is bounded
  to 64 bits. Values wider than 64 bits round-trip within pygob but will not be
  accepted by a standard Go decoder.
- **`time.Duration` decodes as `int`.** Nothing on the wire marks it — see
  [Custom & Named Types](custom-types).
- **Schema evolution is safe.** Unknown fields arriving from Go are ignored;
  missing fields decode as zero. This is a gob protocol guarantee that pygob
  inherits rather than implements.

## Exceptions

```
GobError (base)
├── GobDecodeError   truncated stream, unknown type id, malformed data, end of stream
└── GobEncodeError   unsupported type, missing registration, schema error
```

```python
import pygob
from pygob import GobError, GobDecodeError, GobEncodeError

try:
    pygob.decode(bad_bytes)
except GobDecodeError as e:
    print("decode failed:", e)
```

Catching `GobError` catches both.
