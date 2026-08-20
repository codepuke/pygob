---
title: Overview
---

# pygob

A pure-Python encoder and decoder for Go's [`encoding/gob`](https://pkg.go.dev/encoding/gob)
binary serialization format. No dependencies beyond the standard library.

Any byte stream produced by Go's `encoding/gob` decodes correctly in Python. Any
byte stream produced by pygob decodes correctly in Go.

## Design in one paragraph

Decoded values are plain Python types wherever possible: scalars come back as
`int`, `float`, `bool`, `str`, `bytes`, and `complex` — never wrapper classes.
The one rich decoded type is `GobStruct`, a dict-like object that also carries
its Go type name and schema, which is what makes `decode → encode` round-trips
preserve wire-level fidelity. On the encoding side there is a single wrapper
type, `UInt`, which exists only to resolve the signed/unsigned ambiguity that
Python's `int` cannot express.

## Round-trip

:::examples round-trip

## Where to go next

- [Installation](installation) — `pip` or `uv`.
- [Encoding Values](encoding) — the three ways to describe a struct.
- [Decoding Values](decoding) — what comes back, and how to work with it.
- [Collections](collections) — slices, maps, arrays, and nesting.
- [Streams](streams) — encoding and decoding many values over one stream.
- [Interface Values](interfaces) — `interface{}` fields in both directions.
- [Custom & Named Types](custom-types) — `GobEncoder` types, `time.Time`, `time.Duration`.
- [Type Mapping & Limitations](type-mapping) — the full table, and what pygob does not do.
