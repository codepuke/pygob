---
title: Collections
---

# Collections

## Slices

A Python `list` encodes as a Go slice. The element type is inferred from the
values.

:::examples encode-slice

## Maps

A Python `dict` encodes as a Go map, with both key and element types inferred.

:::examples encode-map

Go map iteration order is unspecified, so two encodings of the same map may
differ byte-for-byte while both being correct. Compare decoded values, never
bytes, when maps are involved.

## Arrays

Gob distinguishes a fixed-size array from a slice. Pass `array_length` to encode
a list as an array.

:::examples encode-array

The fixed length is not preserved on the decoded value: a Go `[3]int` decodes to
an ordinary 3-element Python `list`. Re-encoding with the correct `array_length`
(or a schema using `ArrayOf`) restores it.

## Empty collections

An empty list or dict carries no values to infer element types from, so the types
must be stated explicitly.

:::examples empty-collections

## Structs inside collections

A dict is ambiguous — it could be a map or a struct — so a collection of structs
needs `elem_type` naming the struct's schema.

:::examples slice-of-structs

The same applies to maps with struct values:

```python
from pygob import encode, Schema, GOB_INT

PointSchema = Schema("Point", X=GOB_INT, Y=GOB_INT)
data = encode({"origin": {"X": 0, "Y": 0}}, elem_type=PointSchema)
```

## Structs inside structs

A struct field whose type is another struct takes that struct's `Schema` as its
field type.

:::examples nested-struct

## Collection fields in a schema

When a struct field is itself a collection, describe it with `SliceOf`, `MapOf`,
or `ArrayOf`:

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

With `@gobstruct`, the equivalent annotations are inferred:

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
