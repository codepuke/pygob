// Package main is a Go gob decoder used for Python→Go cross-validation tests.
// It reads gob bytes from stdin, decodes into the named test case's type, and
// writes a JSON result to stdout.
//
// Usage: go run ./tests/go_verify <test_name>
// Example: cat tests/testdata/struct_simple.gob | go run ./tests/go_verify struct_simple
package main

import (
	"bytes"
	"encoding/gob"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/google/uuid"
)

// --- Struct types (must match generate_testdata.go exactly) ---

// Point is a simple two-field struct.
type Point struct {
	X int
	Y int
}

// MixedStruct has fields of several different types.
type MixedStruct struct {
	Name   string
	Age    int
	Score  float64
	Active bool
}

// NestedStruct contains another struct as a field.
type NestedStruct struct {
	Label  string
	Origin Point
}

// PartialStruct is encoded with some fields left at their zero value.
type PartialStruct struct {
	Name  string
	Value int
	Extra float64
}

// Container holds an interface{} field.
type Container struct {
	Name  string
	Value interface{}
}

// HasUUID wraps a uuid.UUID field to test BinaryMarshaler encoding.
type HasUUID struct {
	ID uuid.UUID
}

// EventDuration has a time.Duration field to test GOB_DURATION encoding.
type EventDuration struct {
	Name    string
	Timeout time.Duration
}

// --- Result type ---

type result struct {
	Ok    bool        `json:"ok"`
	Value interface{} `json:"value,omitempty"`
	Error string      `json:"error,omitempty"`
}

func writeOK(value interface{}) {
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(result{Ok: true, Value: value})
}

func writeErr(msg string) {
	_ = json.NewEncoder(os.Stdout).Encode(result{Ok: false, Error: msg})
}

// decode is a generic helper that decodes gob bytes into a value of type T.
func decode[T any](data []byte) (T, error) {
	var v T
	return v, gob.NewDecoder(bytes.NewReader(data)).Decode(&v)
}

func run(testName string, data []byte) {
	switch testName {

	// --- Scalars: bool ---
	case "scalar_bool_true", "scalar_bool_false":
		v, err := decode[bool](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(v)

	// --- Scalars: signed int ---
	case "scalar_int_zero", "scalar_int_positive", "scalar_int_negative", "scalar_int_large":
		v, err := decode[int](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(v)

	// --- Scalars: unsigned int ---
	case "scalar_uint", "scalar_uint_large":
		v, err := decode[uint](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		// Emit as uint64 so json.Marshal doesn't truncate large values.
		writeOK(uint64(v))

	// --- Scalars: float ---
	case "scalar_float", "scalar_float_zero", "scalar_float_negative":
		v, err := decode[float64](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(v)

	// --- Scalars: complex ---
	case "scalar_complex":
		v, err := decode[complex128](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		// encoding/json doesn't handle complex128; split into real/imag.
		writeOK(map[string]float64{"real": real(v), "imag": imag(v)})

	// --- Scalars: string ---
	case "scalar_string", "scalar_string_empty":
		v, err := decode[string](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(v)

	// --- Scalars: bytes ---
	case "scalar_bytes":
		v, err := decode[[]byte](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(v)

	// --- Structs ---
	case "struct_simple":
		v, err := decode[Point](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(v)

	case "struct_mixed":
		v, err := decode[MixedStruct](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(v)

	case "struct_nested":
		v, err := decode[NestedStruct](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(v)

	case "struct_zero_fields":
		v, err := decode[PartialStruct](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(v)

	// --- Slices ---
	case "slice_int", "slice_empty":
		v, err := decode[[]int](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		if v == nil {
			v = []int{}
		}
		writeOK(v)

	case "slice_string":
		v, err := decode[[]string](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		if v == nil {
			v = []string{}
		}
		writeOK(v)

	// --- Arrays ---
	case "array_int":
		v, err := decode[[3]int](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(v)

	// --- Maps ---
	case "map_string_int", "map_empty":
		v, err := decode[map[string]int](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		if v == nil {
			v = map[string]int{}
		}
		writeOK(v)

	case "map_int_string":
		v, err := decode[map[int]string](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		// JSON object keys must be strings; convert int keys explicitly.
		out := make(map[string]string, len(v))
		for k, val := range v {
			out[fmt.Sprintf("%d", k)] = val
		}
		writeOK(out)

	// --- Nested composites ---
	case "nested_slice_of_structs":
		v, err := decode[[]Point](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		if v == nil {
			v = []Point{}
		}
		writeOK(v)

	case "nested_map_of_structs":
		v, err := decode[map[string]Point](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		if v == nil {
			v = map[string]Point{}
		}
		writeOK(v)

	// --- Interface value ---
	case "interface_value":
		v, err := decode[Container](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(v)

	// --- Multi-message stream ---
	// Two Point values encoded with a shared Encoder (type def sent once).
	case "multi_message":
		dec := gob.NewDecoder(bytes.NewReader(data))
		var v1, v2 Point
		if err := dec.Decode(&v1); err != nil {
			writeErr(fmt.Sprintf("decode first message: %v", err))
			return
		}
		if err := dec.Decode(&v2); err != nil {
			writeErr(fmt.Sprintf("decode second message: %v", err))
			return
		}
		writeOK([]interface{}{v1, v2})

	// --- BinaryMarshaler: time.Time ---
	case "scalar_time":
		v, err := decode[time.Time](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(map[string]interface{}{
			"unix": v.Unix(),
			"utc":  v.UTC().Format(time.RFC3339),
		})

	// --- BinaryMarshaler: uuid.UUID ---
	case "scalar_uuid":
		v, err := decode[uuid.UUID](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(v.String())

	case "struct_with_uuid":
		v, err := decode[HasUUID](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(map[string]string{"ID": v.ID.String()})

	// --- time.Duration field ---
	case "struct_duration":
		v, err := decode[EventDuration](data)
		if err != nil {
			writeErr(err.Error())
			return
		}
		writeOK(map[string]interface{}{
			"Name":    v.Name,
			"Timeout": int64(v.Timeout),
		})

	default:
		writeErr(fmt.Sprintf("unknown test case: %q", testName))
	}
}

func main() {
	// Register concrete types that may appear inside interface{} fields.
	gob.Register(Point{})

	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: go_verify <test_name>")
		os.Exit(1)
	}

	data, err := io.ReadAll(os.Stdin)
	if err != nil {
		writeErr(fmt.Sprintf("read stdin: %v", err))
		return
	}

	run(os.Args[1], data)
}
