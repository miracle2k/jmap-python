"""
This implements a custom marshaling system for `attr` models based on
`marshmallow`.

Use the `@marshallable` decorator on a attr class, and it will add two
methods, `cls.unmarshal` and `instance.marshal` - based on the Python 3
type annotations.

See the docstring of `models` to read more about these choices.
"""
import enum
from datetime import datetime
from inspect import isclass
from typing import Union, Dict, List, _ForwardRef, Tuple, Any
import marshmallow
import attr
from marshmallow import ValidationError, post_load, fields, validate

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

    # Is it an enum
    elif issubclass(klass, enum.Enum):
        mm_type = fields.String
        args = {
            'validate': validate.OneOf([c.value for c in klass])
        }

    # Otherwise, see if this type as a direct mapping to a marshmallow field
    else:
        if not klass in TYPE_MAPPING:
            raise ValueError('%s is not a valid type' % klass)
        mm_type = TYPE_MAPPING[klass]
        args = {}

    return mm_type, args


def make_marshmallow_field_from_python_type(klass):
    mm_type, args = get_marshmallow_field_class_from_python_type(klass)
    return mm_type(**args)


def get_marshmallow_field_class_from_mypy_annotation(mypy_type) -> Tuple[Any, Dict]:
    # If a forward reference is given, use the forward reference system of
    # marshmallow. Return a fields.Nested field class with the target type
    # given as a string.
    if isinstance(mypy_type, _ForwardRef):
        return CustomNested, {'nested': mypy_type.__forward_arg__}

    # Resolve MyPy types. Have a look at how this is done in pydantic.fields.py:_populate_sub_fields
    # Indicates a MyPy type; those hide their real type because
    # they do not want `isinstance(foo, Union)` to be abused.
    if hasattr(mypy_type, '__origin__'):
        real_mypy_type = mypy_type.__origin__

        if real_mypy_type is Union:
            # We do not want to support Unions itself; we only allow Optional[foo],
            # which in MyPy internally is Union[foo, None].
            union_types = []
            allow_none = False
            for type_ in mypy_type.__args__:
                if type_ is NoneType:
                    allow_none = True
                else:
                    union_types.append(type_)

            if len(union_types) > 1:
                raise ValueError('Union[] with multiple values not supported by marshalling system.')

            field_type, field_args = \
                get_marshmallow_field_class_from_mypy_annotation(union_types[0])
            return field_type, {**field_args, 'allow_none': allow_none}

        elif isclass(real_mypy_type) and issubclass(real_mypy_type, List):
            item_type = mypy_type.__args__[0]
            item_field_class, item_field_args =\
                get_marshmallow_field_class_from_mypy_annotation(item_type)

            if issubclass(item_field_class, marshmallow.fields.Nested):
                return item_field_class, {'many': True, **item_field_args}
            else:
                field_instance = item_field_class(**item_field_args)
                return marshmallow.fields.List, {'cls_or_instance': field_instance}

        elif isclass(real_mypy_type) and issubclass(real_mypy_type, Dict):
            key_type, value_type = mypy_type.__args__
            key_field = make_marshmallow_field_from_python_type(key_type)
            value_field = make_marshmallow_field_from_python_type(value_type)

            field_type = fields.Dict
            field_args = {
                'keys': key_field,
                'values': value_field,
            }

            return field_type, field_args

    # Is this another marshallable data class?
    field_type, field_args = get_marshmallow_field_class_from_python_type(mypy_type)
    return field_type, field_args


def make_marshmallow_field(attr_field):
    """For the given `attr` field, create a `marshmallow` field.

    We convert the field type, attr validators, if the field is required, or allows None.
    """
    required = True

    field_type, field_args = \
        get_marshmallow_field_class_from_mypy_annotation(attr_field.type)

    # Only do not require it if it has a default.
    if not attr_field.default is attr.NOTHING:
        required = False

    # Convert validators
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

        assert not 'validate'in field_args
        field_args['validate'] = marshmallow_impl


    return field_type(
        data_key=to_camel_case(attr_field.name),
        required=required,
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

