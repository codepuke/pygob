# pygob

A pure-Python encoder and decoder for Go's `gob` binary serialization format.

## Project philosophy

- **Decode to plain Python types wherever possible.** Scalars (int, float, bool, str, bytes, complex) decode to native Python types, never wrapper classes. The only rich decoded type is `GobStruct`, which acts as a dict with attribute access and carries its Go type name and schema.
- **Encode with schemas, not wrappers.** The only wrapper type is `UInt` (for the signed/unsigned int ambiguity). Structs are encoded by pairing a plain dict with a `Schema` object, or by passing a `GobStruct` (which already carries its schema), or via a `@gobstruct` decorated dataclass.
- **Round-tripping works.** `decode → encode` preserves wire-level fidelity for structs because `GobStruct` carries its schema internally.

## Architecture

```
pygob/
├── __init__.py          # Public API re-exports
├── types.py             # GobStruct, UInt, Schema, @gobstruct decorator, type registry
├── codec.py             # Low-level: encode/decode unsigned ints, signed ints, floats, etc.
├── wire.py              # Wire type definitions, bootstrap type IDs (1-23), wireType struct decoding
├── decoder.py           # Decoder class: stream-oriented, reads type defs + values
├── encoder.py           # Encoder class: stream-oriented, emits type defs + values

tests/
├── generate_testdata.go # Go program: encodes values → .gob + .json sidecar files
├── go_verify/
│   └── main.go          # Go program: reads gob from stdin, decodes, writes JSON to stdout
├── testdata/             # Generated .gob and .json files (committed to repo)
├── conftest.py           # Fixtures: testdata loader, go_verify subprocess helper
├── test_codec.py         # Low-level encode/decode of uint/int/float/etc.
├── test_decoder.py       # Full message decoding against Go-generated .gob files
├── test_encoder.py       # Encoding + Python round-trip tests
├── test_go_verify.py     # Cross-validation: Python encodes → Go decodes and verifies
└── test_types.py         # GobStruct, Schema, @gobstruct, UInt

go.mod                    # Root-level, covers both generate_testdata.go and go_verify/
```

## Gob wire format summary

### Encoding primitives

**Unsigned int:** value < 128 → single byte. Otherwise big-endian minimal bytes preceded by one byte = negated byte count. Examples: 0→`00`, 127→`7f`, 128→`ff 80`, 256→`fe 01 00`.

**Signed int:** zigzag into unsigned. `if i < 0: u = (~i << 1) | 1` else `u = i << 1`. Then encode as unsigned.

**Bool:** unsigned int, 0=false, 1=true.

**Float:** IEEE 754 float64 bits, byte-reversed (exponent first for compression), encoded as unsigned int.

**Complex:** two floats (real, imaginary), each encoded as above.

**String / []byte:** unsigned int length prefix, then raw bytes.

### Composite types

**Slice/Array:** unsigned int count, then N elements encoded in sequence.

**Map:** unsigned int count, then N (key, value) pairs.

**Struct:** sequence of (delta-encoded field number, field value) pairs. Delta=0 terminates. Field numbers start at -1 conceptually, so first field transmits delta=1 for field 0. Zero-valued fields are omitted.

### Top-level messages

A gob stream is: `(byteCount message)*`

Each message is either:
- **Type definition:** `int(-typeId) encodingOfWireType` — defines a new type
- **Value:** `int(typeId) encodingOfValue` — sends a value of a known type

Non-struct top-level values are wrapped as a singleton struct field (delta=0, value, then struct terminator 0x00).

### Bootstrap type IDs

```
bool=1, int=2, uint=3, float=4, []byte=5, string=6, complex=7, interface=8
WireType=16, ArrayType=17, CommonType=18, SliceType=19, StructType=20, FieldType=21, fieldTypeSlice=22, MapType=23
User types start at 65 (Go's firstUserId constant). Go's allocator pre-decrements before assigning, so the first type in a Go process actually receives ID 64; Python uses 65 to match Go's stated constant.
```

### wireType structure (what type definitions encode)

wireType is a struct with fields at these positions:
- 0: ArrayT  → {CommonType, Elem typeId, Len int}
- 1: SliceT  → {CommonType, Elem typeId}
- 2: StructT → {CommonType, Field []fieldType}
- 3: MapT    → {CommonType, Key typeId, Elem typeId}
- 4: GobEncoderT → {CommonType}
- 5: BinaryMarshalerT → {CommonType}
- 6: TextMarshalerT → {CommonType}

CommonType is: {Name string, Id int}
fieldType is: {Name string, Id int}

## Design decisions (FINAL — do not deviate)

### Decoded types

| Gob type | Python type | Notes |
|----------|-------------|-------|
| int | `int` | Plain Python int |
| uint | `int` | Plain Python int (signedness tracked in type registry) |
| bool | `bool` | |
| float | `float` | |
| complex | `complex` | |
| string | `str` | |
| []byte | `bytes` | |
| slice | `list` | |
| array | `list` | Array length not preserved on the value |
| map | `dict` | |
| struct | `GobStruct` | Dict-like with `.gob_type` name and attribute access |
| interface | decoded inner value with `.gob_type` on structs | |
| GobEncoder/BinaryMarshaler | `bytes` tagged with type name | |

### Encoding types

| Python type | Gob type | Notes |
|-------------|----------|-------|
| `int` | signed int | Default |
| `UInt(n)` | unsigned int | The ONE wrapper type |
| `bool` | bool | |
| `float` | float64 | |
| `complex` | complex128 | |
| `str` | string | |
| `bytes` | []byte | |
| `list` | slice | Element type inferred or from schema |
| `dict` | map | Key/elem types inferred or from schema |
| `GobStruct` | struct | Schema carried internally |
| plain dict + Schema | struct | Schema provides type name and field types |
| `@gobstruct` dataclass | struct | Schema derived from type annotations |

### UInt

```python
class UInt(int):
    """Marker for unsigned int encoding. Subclasses int so it works everywhere."""
    pass
```

### Schema

```python
PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)
encoder.encode({"X": 22, "Y": 33}, schema=PointSchema)
```

### @gobstruct decorator

```python
@gobstruct("Point")
@dataclass
class Point:
    X: int          # inferred → GOB_INT
    Y: int

@gobstruct("Person")
@dataclass
class Person:
    Name: str       # inferred → GOB_STRING
    Age: int
    Location: Point  # nested struct, schema auto-derived

encoder.encode(Point(X=22, Y=33))
encoder.encode(Person(Name="Alice", Age=30, Location=Point(X=10, Y=20)))
```

### GobStruct

```python
class GobStruct:
    """Decoded gob struct. Acts like a dict with attribute access."""
    gob_type: str               # Go type name, e.g. "Point"
    gob_schema: Schema          # Full field schema for re-encoding
    # supports: result["X"], result.X, dict(result), iter, len, ==
```

### Interface values

Decoded as the inner concrete value. If the concrete value is a struct, it's a `GobStruct` with `.gob_type` set. The encoder needs a type name registry for interfaces:

```python
encoder.register("Point", PointSchema)
encoder.encode_interface(Point(X=22, Y=33))
```

### GobEncoder / BinaryMarshaler / TextMarshaler

Decoded as `GobEncoded(type_name, raw_bytes)` — a small wrapper holding the type name and opaque bytes. Users can register custom codecs:

```python
decoder.register_codec("time.Time", decode_fn=my_time_decoder)
```

## Tooling

- **uv** for project management (NO pip, NO poetry, NO setup.py)
- **pytest** for testing
- **No `src/` directory** — `pygob/` package is at root
- **Go test artifacts** live in `tests/testdata/`, generated by `tests/generate_testdata.go`
- **Root-level `go.mod`** for the Go test generation code

## Commands

```bash
uv run pytest                          # run all tests
uv run pytest tests/test_codec.py      # run one file
uv run pytest -x                       # stop on first failure
uv run pytest tests/test_go_verify.py  # run Go cross-validation tests (requires go on PATH)
go run tests/generate_testdata.go      # regenerate test fixtures
cat tests/testdata/struct_simple.gob | go run ./tests/go_verify struct_simple  # manually test Go verifier
```

## Testing strategy

Three layers of validation, each catching different classes of bugs:

1. **Go→Python (decoder tests):** `tests/testdata/` contains `.gob` files generated by Go (`tests/generate_testdata.go`), plus `.json` sidecar files describing expected decoded values. Python tests decode the `.gob` file and assert against the `.json` sidecar.

2. **Python→Python (round-trip tests):** Encode a Python value → decode it back → verify values match. Catches asymmetric encoder/decoder bugs but NOT symmetric ones.

3. **Python→Go (cross-validation tests):** Encode a Python value → pipe bytes to `go run ./tests/go_verify <test_name>` → assert Go successfully decodes it and the values match. This is the authoritative proof that Python produces Go-compatible output. These tests use `pytest.skip()` when Go isn't on PATH, so they never cause CI failures in Go-free environments.

The Go verifier (`tests/go_verify/main.go`) reads gob from stdin, decodes into the correct Go type for the given test case name, and writes JSON to stdout: `{"ok": true, "value": ...}` or `{"ok": false, "error": "..."}`.

Byte-level comparison against Go `.gob` files is a secondary check used where deterministic (scalars, simple structs). It is NOT reliable for maps (Go's iteration order varies) or any type where encoder choices are valid but non-unique.

## Code style

- Type hints on all public API functions
- Docstrings on all public classes and methods
- No dependencies beyond the standard library
- Raise specific exceptions: `GobDecodeError`, `GobEncodeError`