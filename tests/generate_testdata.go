// Package main generates gob test fixtures for the pygob test suite.
// Run from the project root with: go run tests/generate_testdata.go
package main

import (
	"bytes"
	"encoding/gob"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"time"

	"github.com/google/uuid"
)

// --- Struct types used as test data ---

// Point is a simple two-field struct used in many tests.
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

// Container holds an interface{} field so we can test interface encoding.
type Container struct {
	Name  string
	Value interface{}
}

// HasUUID wraps a uuid.UUID field to test BinaryMarshaler encoding.
type HasUUID struct {
	ID uuid.UUID
}

// M is a convenience alias for building JSON sidecar maps.
type M = map[string]interface{}

func main() {
	// Register concrete types that may appear inside interface{} fields.
	gob.Register(Point{})

	dir := filepath.Join("tests", "testdata")
	if err := os.MkdirAll(dir, 0755); err != nil {
		log.Fatalf("mkdir %s: %v", dir, err)
	}

	// --- Scalar booleans ---

	gen(dir, "scalar_bool_true",
		func(e *gob.Encoder) { must(e.Encode(true)) },
		M{"type": "bool", "value": true})

	gen(dir, "scalar_bool_false",
		func(e *gob.Encoder) { must(e.Encode(false)) },
		M{"type": "bool", "value": false})

	// --- Scalar signed integers ---

	gen(dir, "scalar_int_zero",
		func(e *gob.Encoder) { must(e.Encode(int(0))) },
		M{"type": "int", "value": 0})

	gen(dir, "scalar_int_positive",
		func(e *gob.Encoder) { must(e.Encode(int(42))) },
		M{"type": "int", "value": 42})

	gen(dir, "scalar_int_negative",
		func(e *gob.Encoder) { must(e.Encode(int(-42))) },
		M{"type": "int", "value": -42})

	gen(dir, "scalar_int_large",
		func(e *gob.Encoder) { must(e.Encode(int(1 << 60))) },
		M{"type": "int", "value": int64(1 << 60)})

	// --- Scalar unsigned integers ---

	gen(dir, "scalar_uint",
		func(e *gob.Encoder) { must(e.Encode(uint(42))) },
		M{"type": "uint", "value": uint64(42)})

	gen(dir, "scalar_uint_large",
		func(e *gob.Encoder) { must(e.Encode(uint(1 << 63))) },
		M{"type": "uint", "value": uint64(1 << 63)})

	// --- Scalar floats ---

	gen(dir, "scalar_float",
		func(e *gob.Encoder) { must(e.Encode(float64(3.14159))) },
		M{"type": "float", "value": 3.14159})

	gen(dir, "scalar_float_zero",
		func(e *gob.Encoder) { must(e.Encode(float64(0.0))) },
		M{"type": "float", "value": 0.0})

	gen(dir, "scalar_float_negative",
		func(e *gob.Encoder) { must(e.Encode(float64(-273.15))) },
		M{"type": "float", "value": -273.15})

	// --- Scalar complex ---

	gen(dir, "scalar_complex",
		func(e *gob.Encoder) { must(e.Encode(complex128(1 + 2i))) },
		M{"type": "complex", "value": M{"real": 1.0, "imag": 2.0}})

	// --- Scalar strings ---

	gen(dir, "scalar_string",
		func(e *gob.Encoder) { must(e.Encode("hello, 世界")) },
		M{"type": "string", "value": "hello, 世界"})

	gen(dir, "scalar_string_empty",
		func(e *gob.Encoder) { must(e.Encode("")) },
		M{"type": "string", "value": ""})

	// --- Scalar bytes ---
	// json.Marshal encodes []byte as base64; Python tests must base64-decode.

	gen(dir, "scalar_bytes",
		func(e *gob.Encoder) { must(e.Encode([]byte("hello"))) },
		M{"type": "bytes", "value": []byte("hello")})

	// --- Structs ---

	gen(dir, "struct_simple",
		func(e *gob.Encoder) { must(e.Encode(Point{X: 22, Y: 33})) },
		M{
			"type":     "struct",
			"gob_type": "Point",
			"value":    M{"X": 22, "Y": 33},
			"fields":   M{"X": "int", "Y": "int"},
		})

	gen(dir, "struct_mixed",
		func(e *gob.Encoder) {
			must(e.Encode(MixedStruct{Name: "Alice", Age: 30, Score: 9.5, Active: true}))
		},
		M{
			"type":     "struct",
			"gob_type": "MixedStruct",
			"value":    M{"Name": "Alice", "Age": 30, "Score": 9.5, "Active": true},
			"fields":   M{"Name": "string", "Age": "int", "Score": "float", "Active": "bool"},
		})

	gen(dir, "struct_nested",
		func(e *gob.Encoder) {
			must(e.Encode(NestedStruct{Label: "test", Origin: Point{X: 1, Y: 2}}))
		},
		M{
			"type":     "struct",
			"gob_type": "NestedStruct",
			"value":    M{"Label": "test", "Origin": M{"X": 1, "Y": 2}},
			"fields":   M{"Label": "string", "Origin": "Point"},
		})

	// PartialStruct encoded with Value=0 and Extra=0.0; gob omits zero fields on
	// the wire, so the decoder must supply Python zero values for missing fields.
	gen(dir, "struct_zero_fields",
		func(e *gob.Encoder) {
			must(e.Encode(PartialStruct{Name: "Bob"}))
		},
		M{
			"type":     "struct",
			"gob_type": "PartialStruct",
			"value":    M{"Name": "Bob", "Value": 0, "Extra": 0.0},
			"fields":   M{"Name": "string", "Value": "int", "Extra": "float"},
		})

	// --- Slices ---

	gen(dir, "slice_int",
		func(e *gob.Encoder) { must(e.Encode([]int{1, 2, 3})) },
		M{"type": "slice", "elem_type": "int", "value": []int{1, 2, 3}})

	gen(dir, "slice_string",
		func(e *gob.Encoder) { must(e.Encode([]string{"a", "b", "c"})) },
		M{"type": "slice", "elem_type": "string", "value": []string{"a", "b", "c"}})

	gen(dir, "slice_empty",
		func(e *gob.Encoder) { must(e.Encode([]int{})) },
		M{"type": "slice", "elem_type": "int", "value": []int{}})

	// --- Array ---

	gen(dir, "array_int",
		func(e *gob.Encoder) { must(e.Encode([3]int{10, 20, 30})) },
		M{"type": "array", "elem_type": "int", "value": []int{10, 20, 30}})

	// --- Maps ---

	gen(dir, "map_string_int",
		func(e *gob.Encoder) { must(e.Encode(map[string]int{"one": 1, "two": 2})) },
		M{
			"type":      "map",
			"key_type":  "string",
			"elem_type": "int",
			"value":     map[string]int{"one": 1, "two": 2},
		})

	// map[int]string: JSON object keys are always strings, so the Python test
	// must convert them back to int. The "key_type" field signals this.
	gen(dir, "map_int_string",
		func(e *gob.Encoder) { must(e.Encode(map[int]string{1: "one", 2: "two"})) },
		M{
			"type":      "map",
			"key_type":  "int",
			"elem_type": "string",
			"value":     map[string]string{"1": "one", "2": "two"},
		})

	gen(dir, "map_empty",
		func(e *gob.Encoder) { must(e.Encode(map[string]int{})) },
		M{
			"type":      "map",
			"key_type":  "string",
			"elem_type": "int",
			"value":     map[string]int{},
		})

	// --- Nested composites ---

	gen(dir, "nested_slice_of_structs",
		func(e *gob.Encoder) {
			must(e.Encode([]Point{{X: 1, Y: 2}, {X: 3, Y: 4}}))
		},
		M{
			"type":          "slice",
			"elem_type":     "struct",
			"elem_gob_type": "Point",
			"value":         []M{{"X": 1, "Y": 2}, {"X": 3, "Y": 4}},
		})

	gen(dir, "nested_map_of_structs",
		func(e *gob.Encoder) {
			must(e.Encode(map[string]Point{"a": {X: 1, Y: 2}}))
		},
		M{
			"type":          "map",
			"key_type":      "string",
			"elem_type":     "struct",
			"elem_gob_type": "Point",
			"value":         map[string]M{"a": {"X": 1, "Y": 2}},
		})

	// --- Interface value ---
	// Container.Value is interface{}; the concrete value Point must be registered.

	gen(dir, "interface_value",
		func(e *gob.Encoder) {
			must(e.Encode(Container{Name: "test", Value: Point{X: 1, Y: 2}}))
		},
		M{
			"type":     "struct",
			"gob_type": "Container",
			"value": M{
				"Name":  "test",
				"Value": M{"gob_type": "Point", "X": 1, "Y": 2},
			},
			"fields": M{"Name": "string", "Value": "interface"},
		})

	// --- BinaryMarshaler: time.Time ---
	// time.Time implements encoding.BinaryMarshaler; gob encodes it as opaque bytes.

	goTime := time.Date(2009, time.November, 10, 23, 0, 0, 0, time.UTC)
	gen(dir, "scalar_time",
		func(e *gob.Encoder) { must(e.Encode(goTime)) },
		// Gob uses the unqualified type name; "Time" not "time.Time".
		M{"type": "gob_encoded", "gob_type": "Time", "time_unix": goTime.Unix()})

	// --- BinaryMarshaler: uuid.UUID (github.com/google/uuid) ---
	// uuid.UUID implements encoding.BinaryMarshaler (16 raw bytes).
	// The gob type name is the unqualified Go type name: "UUID".

	testUUID := uuid.MustParse("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
	gen(dir, "scalar_uuid",
		func(e *gob.Encoder) { must(e.Encode(testUUID)) },
		M{"type": "gob_encoded", "gob_type": "UUID", "uuid_str": testUUID.String()})

	gen(dir, "struct_with_uuid",
		func(e *gob.Encoder) { must(e.Encode(HasUUID{ID: testUUID})) },
		M{
			"type":     "struct",
			"gob_type": "HasUUID",
			"value":    M{"ID": M{"type": "gob_encoded", "gob_type": "UUID", "uuid_str": testUUID.String()}},
			"fields":   M{"ID": "UUID"},
		})

	// --- Multi-message stream ---
	// Two values encoded with the same Encoder so the type definition is sent
	// only once and reused on the second value.

	genMulti(dir, "multi_message",
		func(e *gob.Encoder) {
			must(e.Encode(Point{X: 1, Y: 2}))
			must(e.Encode(Point{X: 3, Y: 4}))
		},
		[]interface{}{
			M{
				"type":     "struct",
				"gob_type": "Point",
				"value":    M{"X": 1, "Y": 2},
				"fields":   M{"X": "int", "Y": "int"},
			},
			M{
				"type":     "struct",
				"gob_type": "Point",
				"value":    M{"X": 3, "Y": 4},
				"fields":   M{"X": "int", "Y": "int"},
			},
		})

	fmt.Println("Done generating test data.")
}

// gen encodes a single gob value and writes both the .gob and .json sidecar.
func gen(dir, name string, encode func(*gob.Encoder), sidecar interface{}) {
	var buf bytes.Buffer
	enc := gob.NewEncoder(&buf)
	encode(enc)

	gobPath := filepath.Join(dir, name+".gob")
	if err := os.WriteFile(gobPath, buf.Bytes(), 0644); err != nil {
		log.Fatalf("write %s: %v", gobPath, err)
	}

	jsonBytes, err := json.MarshalIndent(sidecar, "", "  ")
	if err != nil {
		log.Fatalf("marshal json for %s: %v", name, err)
	}
	jsonPath := filepath.Join(dir, name+".json")
	if err := os.WriteFile(jsonPath, jsonBytes, 0644); err != nil {
		log.Fatalf("write %s: %v", jsonPath, err)
	}

	fmt.Printf("  wrote %s (.gob + .json)\n", name)
}

// genMulti is like gen but writes multiple gob values with a shared encoder,
// and the JSON sidecar is an array of per-message expected values.
func genMulti(dir, name string, encode func(*gob.Encoder), sidecar interface{}) {
	gen(dir, name, encode, sidecar)
}

func must(err error) {
	if err != nil {
		log.Fatalf("gob encode: %v", err)
	}
}
