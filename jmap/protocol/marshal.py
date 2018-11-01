"""
This implements a custom marshaling system for `attr` models based on
`marshmallow`.

Use the `@marshallable` decorator on a attr class, and it will add two
methods, `cls.unmarshal` and `instance.marshal` - based on the Python 3
type annotations.

See the docstring of `models` to read more about these choices.
"""

from inspect import isclass
from typing import Union, Dict, List
import marshmallow
import attr
from marshmallow import ValidationError, post_load, fields


NoneType = type(None)


TYPE_MAPPING = {
    str: fields.String,
    float: fields.Float,
    bool: fields.Boolean,
    int: fields.Integer,
    dict: fields.Raw
}


def make_marshmallow_field(attr_field):
    """For the given `attr` field, create a `marshmallow` field.

    We convert the field type, attr validators, if the field is required, or allows None.
    """
    type = attr_field.type

    allow_none = False
    required = True
    is_many = False

    # Resolve MyPy types. Have a look at how this is done in pydantic.fields.py:_populate_sub_fields
    # Indicates a MyPy type; those hide their real type because
    # they do not want `isinstance(foo, Union)` to be abused.
    #
    # The while loop means we do not differ between Optional[List[str]] and List[Optioanl[str]] (TODO).
    while hasattr(type, '__origin__'):
        mypy_type = type.__origin__

        if mypy_type is Union:
            # We do not want to support Unions itself; we only allow Optional[foo],
            # which in MyPy internally is Union[foo, None].
            union_types = []
            for type_ in type.__args__:
                if type_ is NoneType:
                    allow_none = True
                else:
                    union_types.append(type_)

            if len(union_types) > 1:
                raise ValueError('Union[] with multiple values not supported by marshalling system.')

            type = union_types[0]

        elif isclass(mypy_type) and issubclass(mypy_type, List):
            type = type.__args__[0]
            is_many = True

        else:
            # Could not resolve
            break

    # Is this another marshallable data class?
    if hasattr(type, '__marshmallow_schema__'):
        field_type = marshmallow.fields.Nested
        field_args = {'nested': type.__marshmallow_schema__}
    else:
        if not type in TYPE_MAPPING:
            raise ValueError('%s is not a valid type' % type)
        field_type = TYPE_MAPPING[type]
        field_args = {}

    # Only do not require it if it has a default.
    if not attr_field.default is attr.NOTHING:
        required = False

    # Convert validators
    marshmallow_validate = None
    if attr_field.validator:
        def marshmallow_impl(value):
            try:
                # TODO: We could get access to the instance if we used a @validates method
                # in marshmallow.
                attr_field.validator(None, attr_field, value)
            except ValueError as exc:
                # Assume that attrs validators raise a ValueError. Any other exceptions we
                # assume are programming errors and do not catch them.
                raise ValidationError(str(exc))

        marshmallow_validate = marshmallow_impl

    if is_many:
        if field_type == marshmallow.fields.Nested:
            field_args['many'] = True
        else:
            field_args['cls_or_instance'] = field_type
            field_type = marshmallow.fields.List

    return field_type(
        data_key=to_camel_case(attr_field.name),
        required=required,
        allow_none=allow_none,
        validate=marshmallow_validate,
        **field_args
    )


def unmarshall_func(cls, input: Dict):
    schema = cls.__marshmallow_schema__()
    return schema.load(input)


def marshall_func(self):
    schema = self.__marshmallow_schema__()
    return schema.dump(self)


def marshallable(attrclass):
    """Adds a `marshal` classmethod to the attrs class to create the class from
    incoming unstructured data with validation.

    To this end, internally constructs a marshmallow schema based on the type
    definitions, and the attrs validators.
    """
    attr_fields = attr.fields(attrclass)
    marshmallow_fields = {
        field.name: make_marshmallow_field(field)
        for field in attr_fields
    }

    def make_object(self, data):
        # The part where we convert the validated input data into an actual `attr` instance
        # is here, implemented via marshmallow @post_load. That is, marshmallow itself
        # will give us the instance directly. This is easiest as it means that when the class
        # # is used as a relationship, then a marshmallow.fields.Nested() is all we need.
        #
        # Note: Unfortunately, attr will run the validators again, although we already
        # we already did so. We can disable validators globally in attr
        # (attr.set_run_validators(False)) - and then reset it afterwards - but that
        # would not be thread-safe. Open a attr ticket for this. Options include:
        # a) Figure out something with __new__, b) Make attr support a thread-local stack,
        # or contextvar-stack c) a new kind of API they should support to aid marshalling
        # libraries built on top.
        return attrclass(**data)

    marshmallow_fields['_internal_make_object'] = post_load(make_object)

    marshmallow_schema = type(f'{attrclass}Schema', (marshmallow.Schema,), marshmallow_fields)
    attrclass.__marshmallow_schema__ = marshmallow_schema
    attrclass.unmarshal = classmethod(unmarshall_func)
    attrclass.marshal = marshall_func
    return attrclass


def to_camel_case(snake_str):
    components = snake_str.split('_')
    # We capitalize the first letter of each component except the first one
    # with the 'title' method and join them together.
    return components[0] + ''.join(x.title() for x in components[1:])
