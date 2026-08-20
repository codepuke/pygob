---
title: Streams
---

# Streams

Go's `encoding/gob` is designed around a stream carrying many values, not a
single self-contained blob. `Encoder` and `Decoder` model that directly; the
`pygob.encode` / `pygob.decode` convenience functions are one-shot wrappers over
a `BytesIO`.

## Encoding many values

A type definition is emitted the first time a type is used on a stream, and
reused by every later value of that type. Encoding two `Point` values over one
`Encoder` is therefore substantially smaller than encoding them separately.

:::examples stream-multiple-values

This is also why type ids are a property of the stream rather than of the value.
A standalone pygob encode always assigns the first user type id 65; a Go process
that has already registered other types will assign something else. Both are
correct, and both decode identically — which is why byte-for-byte comparison
against a Go-generated file is only meaningful for scalars.

## Decoding until the stream is exhausted

`decode()` raises `GobDecodeError` when there is nothing left to read, so a
read-everything loop is a `try`/`except`:

:::examples decode-stream-until-eof

Any file-like object works — a real file, a socket wrapped in a file object, or a
`BytesIO`. `Decoder` reads only as far as each message requires, so it can be
pointed at a stream that is still being written.
