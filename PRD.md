# PRD: gobdotnet — C# Port of Go's encoding/gob

## Overview

`gobdotnet` is a pure-C# encoder and decoder for Go's `gob` binary serialization format. It follows the spirit of the Python port (`pygob`) while embracing C#-native conventions: strong typing, generics, POCO classes with attributes, and stream-oriented I/O.

The goal is full wire-format compatibility with Go's `encoding/gob` package: any byte stream produced by Go's encoder must decode correctly in C#, and any byte stream produced by the C# encoder must decode correctly in Go.

---

## Project Philosophy

- **Decode to strong types where possible.** Primitives (`long`, `double`, `bool`, `string`, `byte[]`, `Complex`) decode to their native C# counterparts. Structs decode to strongly-typed POCO classes when a type mapping is registered, or to `GobObject` (a `Dictionary<string, object?>` with a `GobType` name) when no mapping is known.
- **Encode with reflection or explicit schemas.** POCOs decorated with `[GobStruct]` infer their schema from properties. Dictionaries require an explicit `GobSchema`. Round-tripping a decoded `GobObject` works because it carries its schema.
- **Wire fidelity.** The encoder produces bytes that Go's decoder accepts without modification.
- **No external dependencies.** Only the .NET BCL (System, System.IO, System.Collections.Generic, System.Numerics, System.Reflection).
- **Target framework:** .NET 8+ (LTS). Use modern C# features (records, pattern matching, nullable reference types, init properties, source generators optional but allowed).

---

## Architecture

```
GobDotNet/
├── GobDotNet.csproj
├── Exceptions.cs           # GobDecodeException, GobEncodeException
├── Types.cs                # GobObject, GobSchema, GobFieldType descriptors, [GobStruct] attribute,
│                           # GobEncoded, UInt64Value (unsigned int marker), SemanticType<T>
├── Codec.cs                # Low-level: read/write uint, int, float, bool, string, bytes
├── Wire.cs                 # WireType structs, bootstrap type IDs, wire type decoding
├── Decoder.cs              # GobDecoder class: stream-oriented, reads type defs + values
├── Encoder.cs              # GobEncoder class: stream-oriented, emits type defs + values
└── Codecs/
    ├── IGobCodec.cs        # IGobCodec<T> interface
    ├── TimeCodec.cs        # DateTimeOffset ↔ Go time.Time (GobEncoder marshaler)
    └── GuidCodec.cs        # Guid ↔ Go UUID (BinaryMarshaler)

GobDotNet.Tests/
├── GobDotNet.Tests.csproj
├── testdata/               # .gob and .json files (shared with or regenerated from Python port)
├── go_verify/              # Reuse Python port's go_verify/main.go verbatim
│   └── main.go
├── generate_testdata.go    # Reuse Python port's generate_testdata.go verbatim
├── go.mod                  # Reuse Python port's go.mod
├── Fixtures.cs             # TestData loader, GoVerify subprocess helper
├── CodecTests.cs           # Low-level uint/int/float/bool/string/bytes encode+decode
├── WireTests.cs            # Wire type struct decoding
├── DecoderTests.cs         # Decode .gob files vs .json sidecars (parametrized)
├── EncoderTests.cs         # Encoding output, type def idempotency, collections, structs
├── RoundTripTests.cs       # Encode → decode → assert value equality
├── GoVerifyTests.cs        # C# encode → Go decode cross-validation
├── TypesTests.cs           # GobObject, GobSchema, [GobStruct], GobEncoded, SemanticType
├── CodecsTests.cs          # TimeCodec, GuidCodec, custom codec registration
└── ErrorTests.cs           # Truncated streams, type mismatches, missing registrations
```

---

## Gob Wire Format Reference

This section is the definitive reference. See also the Go source at `encoding/gob`.

### Primitive Encoding

**Unsigned int:** value < 128 → single byte. Otherwise: header byte = `256 - byte_count`, followed by big-endian minimal bytes.
- `0` → `0x00`
- `127` → `0x7F`
- `128` → `0xFF 0x80`
- `256` → `0xFE 0x01 0x00`
- `65536` → `0xFD 0x01 0x00 0x00`

**Signed int:** zigzag into unsigned. `if i < 0: u = (~i << 1) | 1` else `u = i << 1`. Then encode as unsigned int.
- `0` → `0x00` (zigzag 0)
- `1` → `0x02` (zigzag 2)
- `-1` → `0x01` (zigzag 1)
- `128` → `0xFF 0x00 0x01` (unsigned 256)

**Bool:** unsigned int 0 or 1.

**Float:** IEEE 754 float64 bits → byte-reversed → encoded as unsigned int. This puts the exponent byte first and enables trailing-zero compression for small values.

**Complex:** two floats (real then imaginary).

**String / `[]byte`:** unsigned int length, then raw bytes (UTF-8 for strings).

### Composite Types

**Slice/Array:** unsigned int element count, then N elements.

**Map:** unsigned int pair count, then N key-value pairs.

**Struct:** sequence of (unsigned int delta, field value). Delta = 0 terminates. Field indices start from -1, so the first field always sends delta=1.
- Zero-valued fields are **omitted** entirely. The decoder fills omitted fields with their Go zero values.
- Field ordering is determined by the wire type's field list (alphabetical-ish in Go), not necessarily declaration order.

### Top-Level Messages

A gob stream is a sequence of framed messages: `(uint byteCount, message)*`

Each message is:
- **Type definition:** `int(-typeId) wireType_bytes` — defines a new user type
- **Value:** `int(typeId) payload` — encodes a value of a known type

Non-struct top-level values are wrapped: `0x00 encoded_value` (a singleton struct field with no field number — just the value then struct terminator).

### Bootstrap Type IDs

```
BOOL=1, INT=2, UINT=3, FLOAT=4, BYTES=5, STRING=6, COMPLEX=7, INTERFACE=8
WIRE_TYPE=16, ARRAY_TYPE=17, COMMON_TYPE=18, SLICE_TYPE=19,
STRUCT_TYPE=20, FIELD_TYPE=21, FIELD_TYPE_SLICE=22, MAP_TYPE=23
User types: FIRST_USER_ID = 65
```

Go pre-decrements before assigning, so the first type in a fresh Go process gets ID 64. The C# encoder should also start at 65 (matching Go's stated constant) for test determinism.

### Wire Type Structures

`WireType` is a struct with optional fields at delta positions 0–6:
```
field 0: ArrayT  → {CommonType, Elem typeId, Len int}
field 1: SliceT  → {CommonType, Elem typeId}
field 2: StructT → {CommonType, Field []FieldType}
field 3: MapT    → {CommonType, Key typeId, Elem typeId}
field 4: GobEncoderT → {CommonType}
field 5: BinaryMarshalerT → {CommonType}
field 6: TextMarshalerT → {CommonType}
```

`CommonType = {Name string, Id int}`
`FieldType = {Name string, Id int}`

**Critical:** Collection types (slice, map, array) have an **empty** `CommonType.Name`. Since gob omits zero-value fields, and an empty string is the zero value for string, the `Name` field is **not transmitted** — the `Id` field arrives with a delta of 2 (skipping field 0, the Name). This is one of the most subtle bugs to hit during implementation.

---

## Type System

### Go → C# Type Mapping

| Go Type | C# Type | Notes |
|---------|---------|-------|
| `int` / `int64` | `long` | Go's default int |
| `uint` / `uint64` | `ulong` | Use `GobUInt` wrapper to signal unsigned encoding when ambiguous |
| `bool` | `bool` | |
| `float64` | `double` | |
| `complex128` | `System.Numerics.Complex` | |
| `string` | `string` | |
| `[]byte` | `byte[]` | |
| `[]T` | `List<T>` or `T[]` | Decoded as `List<T>`; encoded from any `IEnumerable<T>` |
| `[N]T` | `T[]` | Fixed-length array; length not preserved in decoded value |
| `map[K]V` | `Dictionary<TKey, TValue>` | |
| struct | Attributed POCO or `GobObject` | `[GobStruct("TypeName")]` for encoding; decoded to POCO if registered |
| `interface{}` | `object?` | Decoded inner value; structs become `GobObject` or registered POCO |
| GobEncoder | `GobEncoded` | Opaque bytes + type name unless codec registered |
| BinaryMarshaler | `GobEncoded` | Same |
| TextMarshaler | `GobEncoded` | Same |

### GobUInt

```csharp
/// <summary>
/// Marker struct for unsigned integer encoding. Wraps a ulong.
/// Use when encoding a value that must be transmitted as gob UINT rather than INT.
/// In practice, fields annotated as ulong or uint in a [GobStruct] are automatically
/// encoded as UINT; GobUInt is only needed when encoding loose values.
/// </summary>
public readonly struct GobUInt(ulong value)
{
    public ulong Value { get; } = value;
    // implicit conversion to/from ulong
}
```

Unlike the Python port, C# has distinct `long` and `ulong` types. Within `[GobStruct]` classes, property type determines signedness automatically:
- `long`, `int`, `short`, `sbyte` → `GOB_INT` (signed)
- `ulong`, `uint`, `ushort`, `byte` → `GOB_UINT` (unsigned)
- `GobUInt` → `GOB_UINT` (for loose encoding via `GobEncoder.Encode(GobUInt value)`)

### GobSchema

```csharp
/// <summary>
/// Describes the gob struct type: its Go name and ordered field descriptors.
/// Used for encoding plain dictionaries and for re-encoding decoded GobObjects.
/// </summary>
public sealed class GobSchema
{
    public string Name { get; }
    public IReadOnlyList<(string Name, GobFieldType Type)> Fields { get; }

    public GobSchema(string name, params (string, GobFieldType)[] fields);

    /// <summary>Derive a schema from a [GobStruct]-attributed type via reflection.</summary>
    public static GobSchema For<T>() where T : class;
    public static GobSchema For(Type t);
}
```

### GobFieldType

Field type descriptors (analogous to Python's int constants and descriptor classes):

```csharp
public abstract class GobFieldType
{
    // Singleton instances for bootstrapped types:
    public static readonly GobFieldType Bool;
    public static readonly GobFieldType Int;    // signed
    public static readonly GobFieldType UInt;   // unsigned
    public static readonly GobFieldType Float;
    public static readonly GobFieldType Bytes;
    public static readonly GobFieldType String;
    public static readonly GobFieldType Complex;
    public static readonly GobFieldType Interface;

    // Composite descriptors:
    public static GobFieldType SliceOf(GobFieldType elem);
    public static GobFieldType MapOf(GobFieldType key, GobFieldType value);
    public static GobFieldType ArrayOf(GobFieldType elem, int length);
    public static GobFieldType StructOf(GobSchema schema);

    // Named primitive types (e.g., type Duration int64):
    public static GobFieldType SemanticInt<T>(Func<long, T> decode, Func<T, long> encode, T zero);
    public static GobFieldType SemanticUInt<T>(Func<ulong, T> decode, Func<T, ulong> encode, T zero);
}
```

Predefined semantic types (in `GobFieldType` or a static `WellKnownTypes` class):
- `GobFieldType.Duration` → `TimeSpan` encoded as `int64` nanoseconds

### GobObject

```csharp
/// <summary>
/// A decoded gob struct with no registered C# type. Acts as an ordered dictionary
/// with string keys and object values, plus the Go type name and schema for re-encoding.
/// </summary>
public sealed class GobObject : IReadOnlyDictionary<string, object?>
{
    public string GobType { get; }       // Go type name, e.g. "Point"
    public GobSchema Schema { get; }     // Full field schema for re-encoding

    public object? this[string key] { get; }
    public bool TryGetValue(string key, out object? value);
    public IEnumerable<string> Keys { get; }
    public IEnumerable<object?> Values { get; }
    // IEnumerable<KeyValuePair<string, object?>> + Count, ContainsKey, GetEnumerator

    // Construction (by decoder and by user):
    public GobObject(string gobType, GobSchema schema, IEnumerable<KeyValuePair<string, object?>> fields);
}
```

### GobEncoded

```csharp
/// <summary>
/// Holds opaque bytes for a Go type that implements GobEncoder, BinaryMarshaler,
/// or TextMarshaler when no C# codec is registered.
/// </summary>
public sealed class GobEncoded(string typeName, byte[] data)
{
    public string TypeName { get; } = typeName;
    public byte[] Data { get; } = data;
}
```

### [GobStruct] Attribute

```csharp
[AttributeUsage(AttributeTargets.Class | AttributeTargets.Struct)]
public sealed class GobStructAttribute(string goTypeName) : Attribute
{
    public string GoTypeName { get; } = goTypeName;
}
```

Usage:

```csharp
[GobStruct("Point")]
public class Point
{
    public long X { get; set; }
    public long Y { get; set; }
}

[GobStruct("Person")]
public class Person
{
    public string Name { get; set; } = "";
    public long Age { get; set; }
    public Point Location { get; set; } = new();
}
```

Schema inference rules from property types:
- `bool` → `GobFieldType.Bool`
- `long` / `int` / `short` / `sbyte` → `GobFieldType.Int`
- `ulong` / `uint` / `ushort` / `byte` → `GobFieldType.UInt`
- `double` / `float` → `GobFieldType.Float`
- `string` → `GobFieldType.String`
- `byte[]` → `GobFieldType.Bytes`
- `System.Numerics.Complex` → `GobFieldType.Complex`
- `TimeSpan` → `GobFieldType.Duration`
- `List<T>` / `T[]` / `IList<T>` → `GobFieldType.SliceOf(...)` (recursive)
- `Dictionary<K, V>` → `GobFieldType.MapOf(...)` (recursive)
- Another `[GobStruct]` class → `GobFieldType.StructOf(GobSchema.For<T>())`
- `object` → `GobFieldType.Interface`

**Field ordering:** Schema fields follow the order of declared properties (use `GetProperties()` sorted by `MetadataToken`, which preserves declaration order in practice on .NET). Verify against Go's alphabetical-ish ordering if cross-language round-trips are needed.

**Field name override** (optional, for Go field name mismatches):
```csharp
[GobField("GoFieldName")]
public long LocalName { get; set; }
```

---

## Public API

### GobEncoder

```csharp
public sealed class GobEncoder : IDisposable
{
    /// <param name="stream">Writable stream; caller retains ownership.</param>
    /// <param name="codecs">Optional custom codecs keyed by Go type name.</param>
    public GobEncoder(Stream stream, IReadOnlyDictionary<string, IGobCodec>? codecs = null);

    /// <summary>
    /// Encode a value. Schema is inferred from [GobStruct] attribute, GobObject.Schema,
    /// or provided explicitly. Throws GobEncodeException on errors.
    /// </summary>
    public void Encode<T>(T value);

    /// <summary>Encode a plain dictionary using an explicit schema.</summary>
    public void Encode(IDictionary<string, object?> value, GobSchema schema);

    /// <summary>
    /// Register a concrete Go type for interface fields.
    /// goName is the fully qualified Go name (e.g. "main.Point").
    /// </summary>
    public void Register(string goName, GobSchema schema);

    /// <summary>Register a codec for a GobEncoder/BinaryMarshaler/TextMarshaler type.</summary>
    public void RegisterCodec<T>(string typeName, IGobCodec<T> codec);

    public void Dispose();
}
```

### GobDecoder

```csharp
public sealed class GobDecoder : IDisposable
{
    /// <param name="stream">Readable stream; caller retains ownership.</param>
    /// <param name="codecs">Optional custom codecs keyed by Go type name.</param>
    public GobDecoder(Stream stream, IReadOnlyDictionary<string, IGobCodec>? codecs = null);

    /// <summary>
    /// Decode the next value from the stream. Returns null at end of stream.
    /// Throws GobDecodeException on malformed data.
    /// </summary>
    public object? Decode();

    /// <summary>
    /// Decode and attempt to cast/map to T.
    /// Registered [GobStruct] types are populated via reflection.
    /// Throws InvalidCastException if decoded type doesn't match T.
    /// </summary>
    public T? Decode<T>();

    /// <summary>
    /// Register a C# type to receive decoded struct values of the named Go type.
    /// Properties are matched by name (case-sensitive by default).
    /// </summary>
    public void Register<T>(string goTypeName) where T : class, new();

    /// <summary>Register a codec for a GobEncoder/BinaryMarshaler/TextMarshaler type.</summary>
    public void RegisterCodec<T>(string typeName, IGobCodec<T> codec);

    public void Dispose();
}
```

### Convenience Functions

```csharp
public static class Gob
{
    /// <summary>Encode value to byte array.</summary>
    public static byte[] Encode<T>(T value, IReadOnlyDictionary<string, IGobCodec>? codecs = null);

    /// <summary>Encode dict + schema to byte array.</summary>
    public static byte[] Encode(IDictionary<string, object?> value, GobSchema schema,
                                 IReadOnlyDictionary<string, IGobCodec>? codecs = null);

    /// <summary>Decode first value from byte array.</summary>
    public static object? Decode(byte[] data, IReadOnlyDictionary<string, IGobCodec>? codecs = null);

    /// <summary>Decode first value from byte array and cast to T.</summary>
    public static T? Decode<T>(byte[] data, IReadOnlyDictionary<string, IGobCodec>? codecs = null);
}
```

### Codec Interface

```csharp
public interface IGobCodec
{
    /// <summary>"gob", "binary", or "text" — matches Go's marshaler interface.</summary>
    string MarshalerType { get; }
}

public interface IGobCodec<T> : IGobCodec
{
    T Decode(byte[] data);
    byte[] Encode(T value);
}
```

Well-known codecs in `GobDotNet.Codecs`:

```csharp
public sealed class TimeCodec : IGobCodec<DateTimeOffset>
{
    public static readonly TimeCodec Instance;
    // Decodes Go time.Time 15-byte binary format:
    // version(1) + seconds_since_year1(8) + nanoseconds(4) + utc_offset_minutes(2)
    // Note: DateTimeOffset has 100ns tick precision; sub-microsecond nanoseconds truncated.
}

public sealed class GuidCodec : IGobCodec<Guid>
{
    public static readonly GuidCodec Instance;
    // Go UUID BinaryMarshaler: 16 raw bytes, big-endian RFC 4122
}

public static class DefaultCodecs
{
    public static IReadOnlyDictionary<string, IGobCodec> All { get; }
    // Keys: "Time", "UUID"
}
```

### Exception Hierarchy

```csharp
public class GobException : Exception
{
    public GobException(string message);
    public GobException(string message, Exception inner);
}

public sealed class GobDecodeException : GobException { ... }
public sealed class GobEncodeException : GobException { ... }
```

---

## Implementation Plan

### Phase 1 — Codec Layer (Codec.cs)

Implement stream-level primitive encoding and decoding. All functions are pure (no stream state beyond position).

**Writer:**
```csharp
internal sealed class GobWriter(Stream stream)
{
    public void WriteUInt(ulong value);
    public void WriteInt(long value);
    public void WriteFloat(double value);
    public void WriteComplex(Complex value);
    public void WriteBool(bool value);
    public void WriteString(string value);
    public void WriteBytes(byte[] value);
    public void WriteRaw(byte[] bytes);
    public byte[] GetBufferedBytes();  // for framing
}
```

**Reader:**
```csharp
internal sealed class GobReader(Stream stream)
{
    public ulong ReadUInt();
    public long ReadInt();
    public double ReadFloat();
    public Complex ReadComplex();
    public bool ReadBool();
    public string ReadString();
    public byte[] ReadBytes();
    public byte[] ReadRaw(int n);
}
```

Unsigned int read algorithm:
```
b = read_byte()
if b <= 0x7F: return b
n = 256 - b  // number of following bytes
read n bytes, big-endian → ulong
```

Float decode: read as uint → to 8-byte big-endian → byte-reverse → IEEE 754.

**Test this layer in isolation before moving on.** Every edge case (0, 127, 128, 255, 256, 2^32, 2^63-1, 2^64-1, -1, -128, NaN, Inf, empty string, unicode) should be unit-tested.

### Phase 2 — Wire Types (Wire.cs)

Define all wire type dataclasses and implement `WireType DecodeWireType(GobReader reader)`.

Bootstrap type ID constants:
```csharp
internal static class BootstrapTypeIds
{
    public const int Bool = 1;
    public const int Int = 2;
    public const int UInt = 3;
    public const int Float = 4;
    public const int Bytes = 5;
    public const int String = 6;
    public const int Complex = 7;
    public const int Interface = 8;
    public const int WireType = 16;
    public const int ArrayType = 17;
    public const int CommonType = 18;
    public const int SliceType = 19;
    public const int StructType = 20;
    public const int FieldType = 21;
    public const int FieldTypeSlice = 22;
    public const int MapType = 23;
    public const int FirstUserId = 65;
}
```

Wire type records:
```csharp
internal record CommonType(string Name, int Id);
internal record FieldWireType(string Name, int Id);
internal record StructWireType(CommonType Common, List<FieldWireType> Fields);
internal record SliceWireType(CommonType Common, int Elem);
internal record ArrayWireType(CommonType Common, int Elem, int Len);
internal record MapWireType(CommonType Common, int Key, int Elem);
internal record MarshalerWireType(CommonType Common);  // shared for gob/binary/text

internal sealed class WireType
{
    public ArrayWireType? ArrayT { get; init; }
    public SliceWireType? SliceT { get; init; }
    public StructWireType? StructT { get; init; }
    public MapWireType? MapT { get; init; }
    public MarshalerWireType? GobEncoderT { get; init; }
    public MarshalerWireType? BinaryMarshalerT { get; init; }
    public MarshalerWireType? TextMarshalerT { get; init; }
}
```

`DecodeWireType` reads delta-encoded fields (same gob struct protocol), dispatches on field number 0–6.

### Phase 3 — Decoder (Decoder.cs)

**Message framing:**
```
uint byteCount = reader.ReadUInt()
byte[] msgBytes = reader.ReadRaw(byteCount)
GobReader msgReader = new GobReader(new MemoryStream(msgBytes))
long typeId = msgReader.ReadInt()
// typeId < 0 → type definition; typeId > 0 → value
```

**Type registry:** `Dictionary<int, WireType?>` where `null` marks bootstrap types (1–23).

**Value dispatch:**
1. Bootstrap INT (2): read singleton wrapper `0x00`, then `ReadInt()` → `long`
2. Bootstrap UINT (3): `0x00` + `ReadUInt()` → `ulong`
3. Bootstrap BOOL (1): `0x00` + `ReadBool()` → `bool`
4. Bootstrap FLOAT (4): `0x00` + `ReadFloat()` → `double`
5. Bootstrap COMPLEX (7): `0x00` + `ReadComplex()` → `Complex`
6. Bootstrap STRING (6): `0x00` + `ReadString()` → `string`
7. Bootstrap BYTES (5): `0x00` + `ReadBytes()` → `byte[]`
8. User type: look up WireType, dispatch on variant

**Struct decoding:** (`DecodeStruct`)
1. Pre-populate all fields with zero values (false, 0, 0.0, "", null, etc.)
2. Read delta-encoded field numbers: `int delta = reader.ReadUInt()` (uint on wire)
3. While delta != 0: `fieldIndex = prevIndex + delta; prevIndex = fieldIndex;`
4. Decode field value by field type ID; advance to next delta
5. Build `GobObject` or populate registered POCO

**Zero values for pre-population:**
- bool → false; long → 0L; ulong → 0UL; double → 0.0; string → ""; byte[] → []
- List → empty list; Dictionary → empty dict; struct → GobObject with empty fields; object → null

**Interface decoding:** (the hardest part — see Lessons Learned)
1. `string typeName = reader.ReadString()` — if empty, nil interface → return null
2. Read inline type definitions (no framing, raw bytes):
   ```
   loop:
     raw_id = reader.ReadInt()  // may throw at EOF → end of inline defs
     if raw_id < 0:
       actual_id = -raw_id
       wt = DecodeWireType(reader)
       typeRegistry[actual_id] = wt
   ```
3. Read concrete value message from outer stream (next framed message)
4. Decode concrete value:
   - Read `uint byteCount` wrapper inside message payload
   - Decode struct payload of that many bytes

**Schema reconstruction:** Convert `StructWireType` → `GobSchema` (walk field type IDs recursively through `typeRegistry`).

### Phase 4 — Encoder (Encoder.cs)

**Type registries:**
- `Dictionary<string, int> _schemaRegistry` — schema name → type ID (dedup)
- `Dictionary<(string, int[]), int> _collectionRegistry` — collection signature → type ID
- `Dictionary<string, (string goName, GobSchema schema)> _interfaceRegistry`
- `int _nextId = BootstrapTypeIds.FirstUserId`

**Message emission:**
```
// Type definition message:
byte[] payload = EncodeWireTypeBytes(wt)
stream.Write(EncodeUInt(payload.Length + sizeOf(typeId)))
stream.Write(EncodeInt(-typeId))
stream.Write(payload)

// Value message:
stream.Write(EncodeUInt(payload.Length + sizeOf(typeId)))
stream.Write(EncodeInt(typeId))
stream.Write(payload)
```

**Struct encoding:**
1. `EmitTypeDefinition(schema)` → typeId (idempotent)
2. Encode payload: `byte[] payload = EncodeStructPayload(value, schema, deferred)`
3. `EmitValue(typeId, payload)`
4. Emit deferred interface messages

**Struct payload encoding:**
- `int prevFieldIndex = -1;`
- For each field (by index in schema.Fields):
  - Get value; if zero-valued → skip
  - `uint delta = fieldIndex - prevFieldIndex;`
  - Write delta as uint; write field value; `prevFieldIndex = fieldIndex`
- Write terminator `0x00`

**Field value encoding** (by field type):
- Primitives: direct `WriteInt`, `WriteUInt`, etc.
- String: `WriteString`; Bytes: `WriteBytes`
- Nested struct: `EncodeStructPayload(...)` (unwrapped, no type-def emission here)
- Slice: `WriteUInt(count)` + each element
- Array: same as slice (length not transmitted)
- Map: `WriteUInt(count)` + each key-value pair
- Interface: `EncodeInterfaceField(value, deferred)`
- SemanticType: convert to wire primitive, encode that

**Interface field encoding:**
1. Get concrete type name (from GobObject.GobType or `[GobStruct]` attribute)
2. Assign inline type ID (separate counter from main; inline IDs can overlap with outer type IDs in Go's implementation — assign from same counter but emit inline without separate message frame)
3. Write to current struct payload:
   - `WriteString(goName)` — fully qualified Go type name
   - `WriteInt(-typeId)` — inline type def signal
   - Write wireType bytes for concrete struct (no framing)
4. Append `(typeId, concretePayload)` to deferred list
5. After struct payload finalized, caller emits deferred messages as framed value messages

**Zero-value detection:**
- `null` → always zero
- `bool` → false
- `long` / `int` / etc. → 0
- `double` → 0.0
- `string` → ""
- `byte[]` → empty array
- `Complex` → `Complex.Zero`
- `TimeSpan` → `TimeSpan.Zero`
- Collections → empty; structs → never zero

**CommonType empty-name shortcut:**
When encoding slice/array/map wire types, `CommonType.Name` is empty (zero value) — omit it entirely, encode Id field with delta=2 (skipping field 0).

### Phase 5 — Public API and Conveniences (Gob.cs, Attributes)

- Implement `Gob.Encode<T>` / `Gob.Decode<T>` as thin wrappers over `GobEncoder` / `GobDecoder` with `MemoryStream`
- Implement schema inference from `[GobStruct]` via reflection in `GobSchema.For<T>()`
- Implement type registration for decoder: store `(string goTypeName, Type csType)` pairs; on struct decode, if name matches, populate a `new T()` via reflection

### Phase 6 — Codecs

Implement `TimeCodec` and `GuidCodec`. Reference Python port's `codecs.py` for wire format details.

`time.Time` binary format (15 bytes, GobEncoder):
```
byte[0]:    version = 1
byte[1-8]:  seconds since January 1, year 1, UTC (int64 big-endian)
byte[9-12]: nanoseconds offset (int32 big-endian) — range [0, 999999999]
byte[13-14]: timezone offset in minutes (int16 big-endian)
             -1 = UTC sentinel (not zone name "UTC")
```

Decode to `DateTimeOffset`; encode from `DateTimeOffset`. Nanoseconds truncated to 100ns ticks.

`uuid.UUID` binary format (16 bytes, BinaryMarshaler): standard RFC 4122 big-endian UUID.

---

## Testing Strategy

Three validation layers, each catching different classes of bugs.

### Layer 1: Go → C# (Decoder Tests)

Reuse the `testdata/` directory from the Python port. The `.gob` and `.json` sidecar files were generated by `tests/generate_testdata.go` and can be used verbatim.

Parametrize `DecoderTests.cs` over all `.gob` files:
```csharp
[Theory]
[MemberData(nameof(AllTestCases))]
public void DecodesGoGeneratedGob(string testName)
{
    var (gobBytes, expected) = TestData.Load(testName);
    var result = Gob.Decode(gobBytes, DefaultCodecs.All);
    AssertMatchesJson(expected, result);
}
```

JSON sidecar schema is the same as used in the Python port. Implement `AssertMatchesJson` in `Fixtures.cs`.

### Layer 2: C# → C# (Round-Trip Tests)

Encode a C# value → decode it → assert equality.

```csharp
[Fact]
public void RoundTrip_StructWithAllFieldTypes()
{
    var original = new Point { X = 22, Y = -33 };
    var bytes = Gob.Encode(original);
    var decoded = Gob.Decode<Point>(bytes);
    Assert.Equal(original.X, decoded!.X);
    Assert.Equal(original.Y, decoded.Y);
}
```

These catch asymmetric encoder/decoder bugs but NOT symmetric ones.

### Layer 3: C# → Go Cross-Validation (GoVerify Tests)

Reuse `tests/go_verify/main.go` from the Python port verbatim (it reads stdin gob → decodes → writes JSON).

```csharp
[SkippableTheory]  // skip if Go not on PATH
[InlineData("scalar_int")]
[InlineData("scalar_string")]
[InlineData("struct_simple")]
// ...
public async Task GoVerifiesEncodedOutput(string testName)
{
    Skip.If(!GoIsAvailable());
    var bytes = EncodeForTest(testName);
    var result = await RunGoVerify(testName, bytes);
    Assert.True(result.Ok, result.Error);
}
```

This is the authoritative proof that C# produces Go-compatible output.

### Test Data Structure

Reuse `tests/testdata/` from the Python port. No need to regenerate. The `.gob` files are Go-generated canonical inputs; the `.json` files describe the expected decoded values with type annotations.

The JSON sidecar format:
```json
{
  "type": "struct",
  "gob_type": "Point",
  "value": { "X": 22, "Y": 33 },
  "fields": { "X": "int", "Y": "int" }
}
```

### Test Coverage Checklist

- [ ] All 8 bootstrap scalar types (bool, int, uint, float, complex, string, bytes)
- [ ] Boundary values: 0, 127/128, -1, max long, min long, max ulong, NaN, +Inf, -Inf
- [ ] Empty string, empty byte[], unicode strings (multi-byte UTF-8)
- [ ] All collection types: slice, array, map, nested
- [ ] Empty collections ([], {})
- [ ] Struct with all field types
- [ ] Nested struct (struct containing struct)
- [ ] Zero-value field omission: encode → decode → omitted fields have zero values
- [ ] Delta encoding: non-sequential field indices (e.g., field 0 present, field 1 omitted, field 2 present)
- [ ] Interface fields: concrete struct, primitive, nil interface
- [ ] Interface type re-registration (same type used in multiple fields)
- [ ] GobEncoder / BinaryMarshaler / TextMarshaler types with and without codec
- [ ] TimeCodec: UTC, positive offset, negative offset, epoch, nanosecond precision loss
- [ ] GuidCodec: all-zeros, random UUID
- [ ] Type definition idempotency: same schema used twice emits one type def
- [ ] Collection type deduplication: `[]int` used in two fields → one type ID
- [ ] Multiple values in single stream (two consecutive encode calls → two decode calls)
- [ ] Streaming: decode before encode completes (if stream is seekable, N values)
- [ ] Error: truncated stream (mid-message, mid-uint, mid-string)
- [ ] Error: unknown type ID
- [ ] Error: type mismatch on encode (field type vs. value type)
- [ ] Error: missing interface registration
- [ ] Error: missing codec for GobEncoder type
- [ ] Go→C# for all testdata/*.gob files (parametrized)
- [ ] C#→Go for all supported test cases (via go_verify)

---

## Lessons Learned from the Python Port

These are the gotchas that cost the most time during Python implementation. Address them explicitly in the C# implementation.

### 1. Interface Fields Use Two Different Framing Schemes

Interface concrete-type definitions are embedded **inline** in the struct payload — not as separate framed messages. The inline defs have no byte-count framing; they flow directly into the struct payload bytes. Decoders must detect EOF (or the struct terminator `0x00`) to know when inline defs end. The concrete value is then a separate framed outer message.

**The deferred message pattern:** The encoder accumulates pending concrete-value messages in a deferred list while encoding the struct payload. After the struct payload is fully built, the caller emits all deferred messages to the outer stream. Getting this ordering wrong corrupts the stream.

### 2. Empty CommonType.Name for Collection Types

Go's gob omits the `Name` field of `CommonType` for collection types (slice, map, array) because it's empty (zero value). This means when encoding/decoding collection wire types, the field delta for the `Id` field is **2** (skipping past the absent `Name` at index 0). This is a silent bug: decoding wrong deltas results in wrong type IDs being read.

**The fix:** In wire type encoding for collections, always emit the Id field with delta=2 instead of delta=1. In decoding, handle the case where field 0 is absent (delta > 1).

### 3. Zero-Value Omission Is Not Optional

Structs with zero-value fields must **omit** those fields from the wire. Sending a zero-value field explicitly is not correct gob — Go may still decode it, but it violates the protocol and Go itself omits zero values. More importantly, when decoding, fields that were never transmitted must be filled with their Go zero value. Pre-populating all fields before the decode loop avoids leaving them as `null` / unset.

### 4. First Field Delta Is 1, Not 0

Field numbering starts from -1, so the first field (index 0) has delta 0-(-1)=1. Delta=0 is the struct terminator. An off-by-one here causes every field after the first to be decoded into the wrong slot.

### 5. Float Encoding Is Byte-Reversed IEEE 754

Go's gob format for floats is NOT standard IEEE 754 big-endian. The 8 bytes of the float64 representation are **reversed** before encoding as a uint. The rationale is that small floats have many trailing zero bytes after reversal, which the uint encoding then compresses. Forgetting the reversal produces wrong values for every float except 0.0 (which encodes identically either way).

### 6. Top-Level Non-Struct Values Are Singleton-Wrapped

When encoding a top-level `int`, `string`, `bool`, etc. (any non-struct), Go wraps it: the value message payload is `0x00 encoded_value`. The `0x00` is the delta=0 struct terminator... but for a singleton, it precedes the value rather than following it. This is because all top-level values in gob are conceptually struct fields; non-structs use this synthetic wrapper. Forgetting it causes decode of `0x00` as the value itself.

### 7. User Type IDs Start at 65, But Go Pre-Decrements

Go's `firstUserId` constant is 65, but Go's type allocator pre-decrements, meaning the first type actually allocated in a Go process is 64. Python matches Go's `firstUserId = 65` for test determinism. The C# encoder should also start at 65. If the C# encoder starts at 64, `scalar_int.gob` and other deterministic tests will mismatch.

### 8. Type Definition Idempotency

The same schema (`SliceOf(GobFieldType.Int)`) used in multiple struct fields must emit **one** type definition message, not two. The encoder tracks schema names and collection signatures in registries and only emits each type definition once. Emitting duplicates causes Go's decoder to return a "type already defined" error.

### 9. Collection Type Registry Uses Structural Signature

Slice, map, and array type IDs are keyed by their structural signature (e.g., `("slice", 2)` for `[]int`) not their position in the schema. Two fields of type `[]string` share a type ID. The registry key must include the full element/key/value structure, not a string name, because the same type can be expressed differently (e.g., a named slice type vs. an anonymous one).

### 10. Nested Struct Fields Are Unwrapped

When encoding a nested struct as a field value within an outer struct, the inner struct's payload is **not** wrapped in a type-def message or a byte-count prefix. It's just the raw delta-encoded field bytes + `0x00` terminator. This differs from top-level struct messages which have the full framing. Getting this wrong corrupts every message that contains nested structs.

### 11. Interface Concrete Value Has an Inner Byte-Count Wrapper

The concrete-value message for an interface has an additional `uint N` prefix inside the message payload, followed by `N` bytes of struct payload, then `0x00`. This is different from top-level struct framing. Go's decoder needs this byte count to parse the inline type defs that precede the concrete value message.

### 12. Bool Must Be Checked Before Int (and Unsigned Before Signed)

In encoding dispatch: `bool` in C# is not an int subclass (unlike Python), but checking the field type descriptor before the runtime value type is still important. When schema says `BOOL`, encode as bool. When inferring from value alone, don't attempt to cast `bool` as `long`. When doing value-type dispatch: check `bool` → `long` / `ulong` in that order; check specific schema type when schema is present.

### 13. Map Encoding Order Is Non-Deterministic

Go's map iteration order is random; Python dicts preserve insertion order. Both are "correct" gob, but byte-level test comparisons of map-containing types will be flaky. Do NOT do byte-level comparison for any type containing a map. Use structural value comparison instead.

### 14. Signed vs. Unsigned Int for the Same Bit Width

Go's `int` and `uint` have the same wire width but different type IDs (INT=2, UINT=3). The schema must track which one a field is. When reconstructing schemas from wire types during decode, record the original type ID to preserve signed/unsigned fidelity.

### 15. timedelta / TimeSpan Precision Mismatch

Go `time.Duration` is `int64` nanoseconds. Python `timedelta` and .NET `TimeSpan` both have 100-nanosecond (tick) precision on .NET, or microsecond precision in Python. Values with sub-tick nanoseconds are truncated on decode. This is expected behavior — document it in xmldoc on `TimeCodec` and `GobFieldType.Duration`.

### 16. The go_verify Test Harness Is Invaluable

Run the Go cross-validation tests frequently, not just at the end. They catch subtle wire-format bugs (wrong byte ordering, wrong framing, wrong delta arithmetic) that Python-only round-trip tests would miss entirely because both encoder and decoder have the same bug.

---

## C#-Specific Design Decisions

### Use Records for Wire Type Structs

`record` types in C# get value-based equality for free, which is useful for testing wire type decoding. Use `record` for `CommonType`, `FieldWireType`, etc.

### Reflection vs. Source Generation

For the initial implementation, **use reflection** in `GobSchema.For<T>()` and in decoder type mapping. A source generator (`[GobStruct]` → compile-time schema) can be added as a follow-on. Reflection is simpler to implement correctly and debug.

### Stream Ownership

Caller always owns the stream. `GobEncoder` and `GobDecoder` should not close the stream on `Dispose()`. They may maintain internal buffers — flush on `Dispose()` if buffering is used.

### Nullable Reference Types

Enable `<Nullable>enable</Nullable>`. Interface values decode as `object?`. Collection elements should be `object?` in `GobObject` values. Annotate all public API carefully.

### BinaryReader/BinaryWriter vs. Manual

Do NOT use `BinaryReader`/`BinaryWriter` — they use little-endian by default and gob uses big-endian with non-standard variable-length encoding. Implement `GobReader`/`GobWriter` manually.

### Struct vs. Class for GobSchema Fields

Use a `(string Name, GobFieldType Type)` value tuple for schema fields rather than a dedicated `GobField` class. This keeps schemas lightweight.

### Sealed Classes

Seal all internal implementation classes (`GobReader`, `GobWriter`, internal registry classes). Mark public API classes sealed where extension doesn't make sense (`GobEncoded`, `GobSchema`).

### Target .NET 8+

Use:
- `System.Numerics.Complex` (available since .NET 1.0)
- `ReadOnlySpan<byte>` for buffer operations in `GobReader`
- `ArgumentNullException.ThrowIfNull(...)` for parameter validation
- Collection expressions `[]` and `[..]` where idiomatic
- `required` properties on `[GobStruct]` POCOs (optional, user's choice)

---

## Project Setup

```xml
<!-- GobDotNet/GobDotNet.csproj -->
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <LangVersion>latest</LangVersion>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <AllowUnsafeBlocks>false</AllowUnsafeBlocks>
    <RootNamespace>GobDotNet</RootNamespace>
  </PropertyGroup>
</Project>

<!-- GobDotNet.Tests/GobDotNet.Tests.csproj -->
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <LangVersion>latest</LangVersion>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="xunit" Version="2.*" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.*" />
    <PackageReference Include="Xunit.SkippableFact" Version="1.*" />  <!-- for GoVerify skip -->
    <ProjectReference Include="../GobDotNet/GobDotNet.csproj" />
  </ItemGroup>
  <ItemGroup>
    <!-- Copy testdata into test output directory -->
    <Content Include="testdata/**" CopyToOutputDirectory="PreserveNewest" />
  </ItemGroup>
</Project>
```

Test runner: **xUnit**. Use `[Theory] + [MemberData]` for parametrized tests. Use `Xunit.SkippableFact` for Go cross-validation tests that skip when Go is not on PATH.

Commands:
```bash
dotnet test                                           # run all tests
dotnet test --filter "Category=GoVerify"              # only cross-validation
dotnet test GobDotNet.Tests --logger "console;verbosity=detailed"
go run tests/generate_testdata.go                     # regenerate testdata (reuse from pygob)
echo "" | go run ./tests/go_verify struct_simple      # manual verifier check
```

---

## Out of Scope (For Now)

- Source generator for `[GobStruct]` → compile-time schema
- AOT / NativeAOT compatibility (requires source gen, not reflection)
- Async streaming API (`EncodeAsync`, `DecodeAsync`)
- Go interface types other than `interface{}` (typed interfaces)
- `chan`, `func`, pointer types (not encoded by gob)
- Recursive/self-referential types
- Versioning / schema evolution across type definition changes
- NuGet package publishing

---

## Acceptance Criteria

The implementation is complete when:

1. All `tests/testdata/*.gob` files decode to the correct values (as specified by `.json` sidecars)
2. All C# → Go cross-validation tests pass (Go decoder accepts C# encoder output)
3. C# → C# round-trip tests pass for all supported types
4. Codec tests pass for `TimeCodec` and `GuidCodec`
5. All error-path tests pass (truncated streams, type mismatches, missing registrations)
6. Zero external dependencies
7. Build with `<Nullable>enable</Nullable>` with no warnings
