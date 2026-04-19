"""Tests for pygob/types.py: UInt, Schema, GobStruct, GobEncoded, @gobstruct."""

from __future__ import annotations

import pytest
from dataclasses import dataclass

from pygob.types import (
    ArrayOf,
    GobEncoded,
    GobStruct,
    GOB_BOOL,
    GOB_BYTES,
    GOB_COMPLEX,
    GOB_FLOAT,
    GOB_INT,
    GOB_STRING,
    GOB_UINT,
    MapOf,
    Schema,
    SliceOf,
    UInt,
    gobstruct,
)


# ---------------------------------------------------------------------------
# UInt
# ---------------------------------------------------------------------------

class TestUInt:
    def test_is_int_subclass(self):
        assert isinstance(UInt(5), int)

    def test_arithmetic(self):
        assert UInt(3) + UInt(4) == 7

    def test_zero(self):
        assert UInt(0) == 0

    def test_distinct_from_plain_int_type(self):
        assert type(UInt(1)) is UInt
        assert type(1) is int


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSchema:
    def test_name_and_fields(self):
        s = Schema("Point", X=GOB_INT, Y=GOB_INT)
        assert s.name == "Point"
        assert s.fields == {"X": GOB_INT, "Y": GOB_INT}

    def test_field_order_preserved(self):
        s = Schema("T", A=GOB_INT, B=GOB_STRING, C=GOB_FLOAT)
        assert list(s.fields.keys()) == ["A", "B", "C"]

    def test_equality(self):
        s1 = Schema("Point", X=GOB_INT, Y=GOB_INT)
        s2 = Schema("Point", X=GOB_INT, Y=GOB_INT)
        assert s1 == s2

    def test_inequality_name(self):
        s1 = Schema("Point", X=GOB_INT)
        s2 = Schema("Other", X=GOB_INT)
        assert s1 != s2

    def test_inequality_fields(self):
        s1 = Schema("Point", X=GOB_INT)
        s2 = Schema("Point", X=GOB_FLOAT)
        assert s1 != s2

    def test_nested_schema(self):
        inner = Schema("Inner", V=GOB_FLOAT)
        outer = Schema("Outer", A=GOB_STRING, B=inner)
        assert outer.fields["B"] is inner

    def test_repr(self):
        s = Schema("P", X=GOB_INT)
        r = repr(s)
        assert "Schema" in r
        assert "'P'" in r
        assert "X" in r

    def test_no_fields(self):
        s = Schema("Empty")
        assert s.fields == {}


# ---------------------------------------------------------------------------
# GobStruct
# ---------------------------------------------------------------------------

class TestGobStruct:
    def _point(self) -> GobStruct:
        schema = Schema("Point", X=GOB_INT, Y=GOB_INT)
        return GobStruct("Point", schema, X=22, Y=33)

    def test_gob_type(self):
        g = self._point()
        assert g.gob_type == "Point"

    def test_gob_schema(self):
        g = self._point()
        assert g.gob_schema.name == "Point"

    def test_getitem(self):
        g = self._point()
        assert g["X"] == 22
        assert g["Y"] == 33

    def test_getattr(self):
        g = self._point()
        assert g.X == 22
        assert g.Y == 33

    def test_getattr_missing_raises(self):
        g = self._point()
        with pytest.raises(AttributeError):
            _ = g.Z

    def test_getitem_missing_raises(self):
        g = self._point()
        with pytest.raises(KeyError):
            _ = g["Z"]

    def test_iter(self):
        g = self._point()
        assert set(g) == {"X", "Y"}

    def test_len(self):
        g = self._point()
        assert len(g) == 2

    def test_contains(self):
        g = self._point()
        assert "X" in g
        assert "Z" not in g

    def test_keys_values_items(self):
        g = self._point()
        assert set(g.keys()) == {"X", "Y"}
        assert set(g.values()) == {22, 33}
        assert dict(g.items()) == {"X": 22, "Y": 33}

    def test_dict_conversion(self):
        g = self._point()
        assert dict(g) == {"X": 22, "Y": 33}

    def test_equality_gobstruct(self):
        g1 = self._point()
        g2 = self._point()
        assert g1 == g2

    def test_equality_dict(self):
        g = self._point()
        assert g == {"X": 22, "Y": 33}

    def test_inequality_different_type(self):
        schema = Schema("Point", X=GOB_INT, Y=GOB_INT)
        g1 = GobStruct("Point", schema, X=22, Y=33)
        g2 = GobStruct("Other", schema, X=22, Y=33)
        assert g1 != g2

    def test_inequality_different_values(self):
        schema = Schema("Point", X=GOB_INT, Y=GOB_INT)
        g1 = GobStruct("Point", schema, X=22, Y=33)
        g2 = GobStruct("Point", schema, X=22, Y=99)
        assert g1 != g2

    def test_repr(self):
        g = self._point()
        r = repr(g)
        assert "GobStruct" in r
        assert "'Point'" in r
        assert "X=22" in r

    def test_setitem(self):
        g = self._point()
        g["X"] = 100
        assert g.X == 100

    def test_setattr(self):
        g = self._point()
        g.Y = 200
        assert g["Y"] == 200

    def test_get(self):
        g = self._point()
        assert g.get("X") == 22
        assert g.get("Z") is None
        assert g.get("Z", -1) == -1


# ---------------------------------------------------------------------------
# GobEncoded
# ---------------------------------------------------------------------------

class TestGobEncoded:
    def test_fields(self):
        ge = GobEncoded("time.Time", b"\x01\x02\x03")
        assert ge.type_name == "time.Time"
        assert ge.data == b"\x01\x02\x03"

    def test_equality(self):
        a = GobEncoded("time.Time", b"\x01")
        b = GobEncoded("time.Time", b"\x01")
        assert a == b

    def test_inequality_name(self):
        a = GobEncoded("time.Time", b"\x01")
        b = GobEncoded("other.Type", b"\x01")
        assert a != b

    def test_inequality_data(self):
        a = GobEncoded("time.Time", b"\x01")
        b = GobEncoded("time.Time", b"\x02")
        assert a != b

    def test_repr(self):
        ge = GobEncoded("time.Time", b"\x01")
        assert "GobEncoded" in repr(ge)
        assert "time.Time" in repr(ge)


# ---------------------------------------------------------------------------
# @gobstruct decorator
# ---------------------------------------------------------------------------

class TestGobstructDecorator:
    def test_basic_schema(self):
        @gobstruct("Point")
        @dataclass
        class Point:
            X: int
            Y: int

        schema = Point.__gob_schema__
        assert schema.name == "Point"
        assert schema.fields["X"] == GOB_INT
        assert schema.fields["Y"] == GOB_INT

    def test_all_primitive_types(self):
        @gobstruct("All")
        @dataclass
        class All:
            b: bool
            i: int
            u: UInt
            f: float
            s: str
            by: bytes
            c: complex

        schema = All.__gob_schema__
        assert schema.fields["b"] == GOB_BOOL
        assert schema.fields["i"] == GOB_INT
        assert schema.fields["u"] == GOB_UINT
        assert schema.fields["f"] == GOB_FLOAT
        assert schema.fields["s"] == GOB_STRING
        assert schema.fields["by"] == GOB_BYTES
        assert schema.fields["c"] == GOB_COMPLEX

    def test_nested_gobstruct(self):
        @gobstruct("Inner")
        @dataclass
        class Inner:
            V: float

        @gobstruct("Outer")
        @dataclass
        class Outer:
            Name: str
            Loc: Inner

        schema = Outer.__gob_schema__
        assert schema.fields["Name"] == GOB_STRING
        nested = schema.fields["Loc"]
        assert isinstance(nested, Schema)
        assert nested.name == "Inner"
        assert nested.fields["V"] == GOB_FLOAT

    def test_field_order_preserved(self):
        @gobstruct("Ordered")
        @dataclass
        class Ordered:
            A: int
            B: str
            C: float

        schema = Ordered.__gob_schema__
        assert list(schema.fields.keys()) == ["A", "B", "C"]

    def test_requires_dataclass(self):
        with pytest.raises(TypeError, match="dataclass"):
            @gobstruct("Bad")
            class NotADataclass:
                X: int

    def test_unknown_annotation_raises(self):
        with pytest.raises(TypeError, match="Cannot infer gob type"):
            @gobstruct("Bad")
            @dataclass
            class Bad:
                X: list  # list not supported without schema

    def test_empty_dataclass(self):
        @gobstruct("Empty")
        @dataclass
        class Empty:
            pass

        schema = Empty.__gob_schema__
        assert schema.name == "Empty"
        assert schema.fields == {}


# ---------------------------------------------------------------------------
# SliceOf, MapOf, ArrayOf
# ---------------------------------------------------------------------------

class TestCollectionDescriptors:
    def test_sliceof_repr(self):
        assert repr(SliceOf(GOB_INT)) == "SliceOf(2)"

    def test_sliceof_equality(self):
        assert SliceOf(GOB_INT) == SliceOf(GOB_INT)
        assert SliceOf(GOB_INT) != SliceOf(GOB_STRING)
        assert SliceOf(GOB_INT) != SliceOf(GOB_FLOAT)

    def test_sliceof_nested(self):
        inner = SliceOf(GOB_INT)
        outer = SliceOf(inner)
        assert outer == SliceOf(SliceOf(GOB_INT))
        assert outer != SliceOf(GOB_INT)

    def test_sliceof_schema_elem(self):
        inner_schema = Schema("Point", X=GOB_INT, Y=GOB_INT)
        desc = SliceOf(inner_schema)
        assert desc.elem_type is inner_schema
        assert desc == SliceOf(Schema("Point", X=GOB_INT, Y=GOB_INT))

    def test_mapof_repr(self):
        assert repr(MapOf(GOB_STRING, GOB_INT)) == "MapOf(6, 2)"

    def test_mapof_equality(self):
        assert MapOf(GOB_STRING, GOB_INT) == MapOf(GOB_STRING, GOB_INT)
        assert MapOf(GOB_STRING, GOB_INT) != MapOf(GOB_INT, GOB_STRING)
        assert MapOf(GOB_STRING, GOB_INT) != MapOf(GOB_STRING, GOB_FLOAT)

    def test_arrayof_repr(self):
        assert repr(ArrayOf(GOB_FLOAT, 3)) == "ArrayOf(4, 3)"

    def test_arrayof_equality(self):
        assert ArrayOf(GOB_INT, 5) == ArrayOf(GOB_INT, 5)
        assert ArrayOf(GOB_INT, 5) != ArrayOf(GOB_INT, 4)
        assert ArrayOf(GOB_INT, 5) != ArrayOf(GOB_FLOAT, 5)

    def test_hashable(self):
        # All descriptors must be usable in sets/as dict keys
        s = {SliceOf(GOB_INT), SliceOf(GOB_INT), SliceOf(GOB_STRING)}
        assert len(s) == 2
        m = {MapOf(GOB_STRING, GOB_INT): "ok"}
        assert m[MapOf(GOB_STRING, GOB_INT)] == "ok"
        a = {ArrayOf(GOB_INT, 3): True}
        assert a[ArrayOf(GOB_INT, 3)] is True


# ---------------------------------------------------------------------------
# @gobstruct with collection annotations
# ---------------------------------------------------------------------------

class TestGobstructCollections:
    def test_list_int(self):
        @gobstruct("Items")
        @dataclass
        class Items:
            Values: list[int]

        schema = Items.__gob_schema__
        assert schema.fields["Values"] == SliceOf(GOB_INT)

    def test_list_str(self):
        @gobstruct("Tags")
        @dataclass
        class Tags:
            Names: list[str]

        schema = Tags.__gob_schema__
        assert schema.fields["Names"] == SliceOf(GOB_STRING)

    def test_dict_str_int(self):
        @gobstruct("Counter")
        @dataclass
        class Counter:
            Counts: dict[str, int]

        schema = Counter.__gob_schema__
        assert schema.fields["Counts"] == MapOf(GOB_STRING, GOB_INT)

    def test_dict_int_str(self):
        @gobstruct("Lookup")
        @dataclass
        class Lookup:
            Labels: dict[int, str]

        schema = Lookup.__gob_schema__
        assert schema.fields["Labels"] == MapOf(GOB_INT, GOB_STRING)

    def test_list_of_gobstruct(self):
        @gobstruct("Point")
        @dataclass
        class Point:
            X: int
            Y: int

        @gobstruct("Cloud")
        @dataclass
        class Cloud:
            Points: list[Point]

        schema = Cloud.__gob_schema__
        field_desc = schema.fields["Points"]
        assert isinstance(field_desc, SliceOf)
        assert field_desc.elem_type == Point.__gob_schema__

    def test_dict_str_gobstruct(self):
        @gobstruct("Point")
        @dataclass
        class Point:
            X: int
            Y: int

        @gobstruct("NamedPoints")
        @dataclass
        class NamedPoints:
            Map: dict[str, Point]

        schema = NamedPoints.__gob_schema__
        field_desc = schema.fields["Map"]
        assert isinstance(field_desc, MapOf)
        assert field_desc.key_type == GOB_STRING
        assert field_desc.val_type == Point.__gob_schema__

    def test_mixed_fields(self):
        """Struct with both plain and collection fields."""
        @gobstruct("Mixed")
        @dataclass
        class Mixed:
            Name: str
            Count: int
            Tags: list[str]
            Scores: dict[str, float]

        schema = Mixed.__gob_schema__
        assert schema.fields["Name"] == GOB_STRING
        assert schema.fields["Count"] == GOB_INT
        assert schema.fields["Tags"] == SliceOf(GOB_STRING)
        assert schema.fields["Scores"] == MapOf(GOB_STRING, GOB_FLOAT)

    def test_unsupported_annotation_raises(self):
        """Bare list (no type arg) still raises TypeError."""
        with pytest.raises(TypeError):
            @gobstruct("Bad")
            @dataclass
            class Bad:
                X: list  # no type arg

    def test_optional_annotation_raises(self):
        """Optional[int] is not a supported annotation."""
        from typing import Optional
        with pytest.raises(TypeError):
            @gobstruct("Bad")
            @dataclass
            class Bad:
                X: Optional[int]  # noqa: UP007
