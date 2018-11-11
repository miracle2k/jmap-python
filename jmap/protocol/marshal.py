"""
This implements a custom marshaling system for `attr` models based on
`marshmallow`.

Use the `@marshallable` decorator on a attr class, and it will add two
methods, `cls.unmarshal` and `instance.marshal` - based on the Python 3
type annotations.

See the docstring of `models` to read more about these choices.
"""

from datetime import datetime
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
    datetime: fields.DateTime
}


def get_marshmallow_field_class_from_python_type(klass):
    # It is already a marshmallow type?
    if isinstance(klass, fields.Field):
        return klass, {}

    # Is this another marshallable data class?
    if hasattr(klass, '__marshmallow_schema__'):
        mm_type = CustomNested
        args = {'nested': klass.__marshmallow_schema__}
    else:
        if not klass in TYPE_MAPPING:
            raise ValueError('%s is not a valid type' % klass)
        mm_type = TYPE_MAPPING[klass]
        args = {}

    return mm_type, args


def make_marshmallow_field_from_class(klass):
    mm_type, args = get_marshmallow_field_class_from_python_type(klass)
    return mm_type(**args)


def get_marshmallow_field_class_from_mypy_annotation(mypy_type):
    is_many = False

    # Resolve MyPy types. Have a look at how this is done in pydantic.fields.py:_populate_sub_fields
    # Indicates a MyPy type; those hide their real type because
    # they do not want `isinstance(foo, Union)` to be abused.
    #
    # The while loop means we do not differ between Optional[List[str]] and List[Optional[str]] (TODO).
    while hasattr(mypy_type, '__origin__'):
        real_mypy_type = mypy_type.__origin__

        if real_mypy_type is Union:
            # We do not want to support Unions itself; we only allow Optional[foo],
            # which in MyPy internally is Union[foo, None].
            union_types = []
            for type_ in mypy_type.__args__:
                if type_ is NoneType:
                    allow_none = True
                else:
                    union_types.append(type_)

            if len(union_types) > 1:
                raise ValueError('Union[] with multiple values not supported by marshalling system.')

            mypy_type = union_types[0]

        elif isclass(real_mypy_type) and issubclass(real_mypy_type, List):
            mypy_type = mypy_type.__args__[0]
            is_many = True

        elif isclass(real_mypy_type) and issubclass(real_mypy_type, Dict):
            key_type, value_type = mypy_type.__args__
            key_field = make_marshmallow_field_from_class(key_type)
            value_field = make_marshmallow_field_from_class(value_type)

            field_type = fields.Dict
            field_args = {
                'keys': key_field,
                'values': value_field,
            }

            return field_type, field_args, False

        else:
            # Could not resolve
            break

    # Is this another marshallable data class?
    field_type, field_args = get_marshmallow_field_class_from_python_type(mypy_type)
    return field_type, field_args, is_many


def make_marshmallow_field(attr_field):
    """For the given `attr` field, create a `marshmallow` field.

    We convert the field type, attr validators, if the field is required, or allows None.
    """
    allow_none = False
    required = True

    field_type, field_args, is_many = \
        get_marshmallow_field_class_from_mypy_annotation(attr_field.type)

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
        if issubclass(field_type, marshmallow.fields.Nested):
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


class CustomNested(fields.Nested):
    """
    Like marshmallow's Nested, but when serializing, when given a dict
    (rather than a model), just outputs the dict as given.
    """

    def _serialize(self, nested_obj, attr, obj, **kwargs):
        dump_dict = False
        if self.many and nested_obj and len(nested_obj) and isinstance(nested_obj[0], dict):
            dump_dict = True
        elif not self.many and isinstance(nested_obj, dict):
            dump_dict = True
        if dump_dict:
            return nested_obj

        # Serialize as normal
        return super()._serialize(nested_obj, attr, obj, **kwargs)

