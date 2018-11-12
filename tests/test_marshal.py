"""
Test our custom marshmallow based system to validate input.
"""
import enum

import attr
import pytest
from marshmallow import ValidationError
from jmap.protocol.marshal import marshallable, custom_marshal
from typing import Optional, List, Dict

from jmap.protocol.models import model


def test_optional():
    """
    Ensure tying.Optional[] does it's job.
    """

    @marshallable
    @attr.s(auto_attribs=True)
    class Foo:
        role: Optional[int]

    with pytest.raises(ValidationError):
        Foo.unmarshal({})

    assert Foo.unmarshal({'role': None}) == Foo(role=None)

    with pytest.raises(ValidationError):
        # Ensure type is passed through properly
        Foo.unmarshal({'role': True})

    assert Foo.unmarshal({'role': 5}) == Foo(role=5)


def test_required():
    """
    Test required status is properly  handled
    """

    @marshallable
    @attr.s(auto_attribs=True)
    class Bar:
        foo: int

    @marshallable
    @attr.s(auto_attribs=True)
    class Baz:
        foo: int = 3

    with pytest.raises(ValidationError):
        Bar.unmarshal({})
    assert Baz.unmarshal({}) == Baz()
    assert Baz.unmarshal({'foo': 1}) == Baz(foo=1)


def test_validators():
    """
    Ensure that the attrs validators are used during marshall.
    """

    def must_be_42(self, attribute, value):
        if not value == 42:
            raise ValueError('value is not 42')

    @marshallable
    @attr.s(auto_attribs=True)
    class Bar:
        foo: float = attr.ib(validator=must_be_42)

    with pytest.raises(ValidationError):
        Bar.unmarshal({'foo': 2})
    Bar.unmarshal({'foo': 42})


def test_nested_objects():
    """
    Ensure that we can nest objects.
    """

    @marshallable
    @attr.s(auto_attribs=True)
    class Foo:
        name: str

    @marshallable
    @attr.s(auto_attribs=True)
    class Bar:
        foo: Foo

    with pytest.raises(ValidationError):
        Bar.unmarshal({'foo': {'name': 2}})
    assert Bar.unmarshal({'foo': {'name': 'test'}}) == Bar(foo=Foo(name='test'))


def test_list_of_primitive():
    """
    Test a list of a primitive.
    """

    @marshallable
    @attr.s(auto_attribs=True)
    class Foo:
        names: List[str]

    assert Foo.unmarshal({'names': ['a', 'b']}) == Foo(names=['a', 'b'])


def test_list_of_optional():
    """
    Test List[Optional[*] vs Optional[List[*]]
    """

    @marshallable
    @attr.s(auto_attribs=True)
    class OptionalItem:
        names: List[Optional[str]]

    assert OptionalItem.unmarshal({'names': ['a', None]}) == OptionalItem(names=['a', None])
    with pytest.raises(ValidationError):
        assert OptionalItem.unmarshal({'names': None}) == OptionalItem(names=None)

    @marshallable
    @attr.s(auto_attribs=True)
    class OptionalList:
        names: Optional[List[str]]

    with pytest.raises(ValidationError):
        assert OptionalList.unmarshal({'names': ['a', None]}) == OptionalList(names=['a', None])
    assert OptionalList.unmarshal({'names': None}) == OptionalList(names=None)


def test_dict_of_primitive():
    """
    Test a dict of a primitive.
    """

    @marshallable
    @attr.s(auto_attribs=True)
    class Foo:
        names: Dict[str, bool]

    assert Foo.unmarshal({'names': {'a': True, 'b': False}}) == Foo(names={'a': True, 'b': False})


def test_forward_refs():
    """
    Test forward references.
    """

    @marshallable
    @attr.s(auto_attribs=True)
    class Foo:
        id: int
        sub: Optional["self"]

    assert Foo.unmarshal({'id': 1, 'sub': {'id': 2, 'sub': None}}) == Foo(id=1, sub=Foo(id=2, sub=None))


def test_enum():
    """
    Test Enums.
    """

    class Color(enum.Enum):
        red = 'red'
        green = 'green'


    @marshallable
    @attr.s(auto_attribs=True)
    class Foo:
        v: Color

    with pytest.raises(ValidationError):
        assert Foo.unmarshal({'v': 1}) == Foo(v=1)

    with pytest.raises(ValidationError):
        assert Foo.unmarshal({'v': 'redd'}) == Foo(v='redd')

    assert Foo.unmarshal({'v': 'red'}) == Foo(v='red')


def test_custom_marshal_functions():
    """
    Test custom marshal/unmarshal functions for a field.
    """

    def dump(data, instance, field):
        # Instead of {v: 1}, output {1: v}
        data[getattr(instance, field.name)] = field.name
        return data

    def load(data, field):
        # Consume all other keys, sum length of all
        sum = 0
        for k, v in data.items():
            sum += len(v)

        return sum, list(data.keys())

    @model
    class Foo:
        v: int = attr.ib(metadata={'marshal': custom_marshal(dump, load)})

    assert Foo.marshal(Foo(v=1)) == {1: 'v'}

    assert Foo.unmarshal({'x': 'red', 'y': 'blue'}) == Foo(v=7)
