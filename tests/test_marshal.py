"""
Test our custom marshmallow based system to validate input.
"""

import attr
import pytest
from marshmallow import ValidationError
from jmap.protocol.marshal import marshallable
from typing import Optional, List, Dict


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


def test_dict_of_primitive():
    """
    Test a dict of a primitive.
    """

    @marshallable
    @attr.s(auto_attribs=True)
    class Foo:
        names: Dict[str, bool]

    assert Foo.unmarshal({'names': {'a': True, 'b': False}}) == Foo(names={'a': True, 'b': False})
