"""
This implements a custom marshaling system for `attr` models based on
`marshmallow`.

Use the `@marshallable` decorator on a attr class, and it will add two
methods, `cls.unmarshal` and `instance.marshal` - based on the Python 3
type annotations.


Ultimately, the result will be that:

1. You have the unmodified attr behaviour, which means:

    - Creating a model instance will validate attribute existence,
      and run custom validators, but will not validate types.

    - Properties which have a default value need not be specified.

2. The marshmallow deserialization helpers will:

    - Will also validate the property keys, like attrs.
    - It will run any attr validation code.
    - It will further validate the types of all properties, including
      nested structures.
    - Will convert from camelCase keys to snake_keys names in Python,
      and accounts for some reserved identifiers like "from" as well.
    - It can have some custom logic.
    - Optional properties will be skipped by marshmallow, and as such
      will be initialized by `attrs` to their `attrs`-defaults.
    - The client-side version will fail if a server-side attribute
      is provided.

3. The marshmallow serialization helpers will:

    - Enforce that the values inside the `attrs`-model are of the
      correct type.
    - Converts from internal snake_case properties to camelCase in
      JSON, and accounts for Python reserved identifier-avoiding
      renames such as "from_".
    - The client-side version will ignore any server-side attributes.
-
"""

import enum
import re
from collections import Counter
from datetime import datetime
from functools import partial
from inspect import isclass
from typing import Union, Dict, List, _ForwardRef, Tuple, Any, Optional
import marshmallow
from marshmallow import ValidationError, post_load, fields, post_dump, Schema

from jmap.models.attrs import NOTHING, fields as get_fields, attrs, attrib
from jmap.models.fields import JmapDateTime
from jmap.models.utils import get_set_attrs


NoneType = type(None)


# marshmallow will not dump those into the output
Missing = marshmallow.missing


TYPE_MAPPING = {
    str: fields.String,
    float: fields.Float,
    bool: fields.Boolean,
    int: fields.Integer,
    datetime: JmapDateTime,
}


@attrs
class custom_marshal:
    marshal = attrib()
    unmarshal = attrib()


def get_marshmallow_field_class_from_python_type(klass):
    # It is already a marshmallow type?
    if isinstance(klass, fields.Field):
        return klass, {}

    # Is this another marshallable data class?
    if hasattr(klass, '__marshmallow_schemas__'):
        mm_type = CustomNested
        args = {'nested': klass}

    # Is it an enum
    elif isinstance(klass, type) and issubclass(klass, enum.Enum):
        mm_type = EnumField
        args = {'enum': klass, 'by_value': True}

    # Otherwise, see if this type as a direct mapping to a marshmallow field
    else:
        if not klass in TYPE_MAPPING:
            raise ValueError('%s is not a valid type' % klass)
        mm_type = TYPE_MAPPING[klass]
        args = {}

    return mm_type, args


def get_marshmallow_field_class_from_mypy_annotation(mypy_type) -> Tuple[Any, Dict]:
    # If a forward reference is given, use the forward reference system of
    # marshmallow. Return a fields.Nested field class with the target type
    # given as a string.
    if isinstance(mypy_type, _ForwardRef):
        return CustomNested, {'nested': mypy_type.__forward_arg__}

    # Any types we read as "Raw"
    if mypy_type is Any:
        return fields.Raw, {}

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
                field_type = PolyField
                field_args = {
                    'union_types': {
                        t: make_marshmallow_field_from_python_type(t)
                        for t in union_types
                    },
                    'allow_none': allow_none
                }
                return field_type, field_args

            else:
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
            value_field = make_marshmallow_field_class_from_mypy_annotation(value_type)

            field_type = fields.Dict
            field_args = {
                'keys': key_field,
                'values': value_field,
            }

            return field_type, field_args

    # Is this another marshallable data class?
    field_type, field_args = get_marshmallow_field_class_from_python_type(mypy_type)
    return field_type, field_args


def make_marshmallow_field_from_python_type(klass):
    mm_type, args = get_marshmallow_field_class_from_python_type(klass)
    return mm_type(**args)


def make_marshmallow_field_class_from_mypy_annotation(mypy_type) -> Tuple[Any, Dict]:
    mm_type, args = get_marshmallow_field_class_from_mypy_annotation(mypy_type)
    return mm_type(**args)


def make_marshmallow_field(attr_field) -> Optional[fields.Field]:
    """For the given `attr` field, create a `marshmallow` field.

    We convert the field type, attr validators, if the field is required, or allows None.
    """

    required = True

    custom_marshal = attr_field.metadata.get('marshal')

    # Handle the case of the field wanting to do custom marshalling
    if custom_marshal:
        field_type = CustomUnmarshalField
        field_args = {
            'attr_field': attr_field,
            'unmarshal_func': custom_marshal.unmarshal,
            # We only load it, because dumping is done in a post_dump hook.
            'load_only': True
        }

    else:
        field_type, field_args = \
            get_marshmallow_field_class_from_mypy_annotation(attr_field.type)

    # Only do not require it if it has a default. Effectively, marshmallow
    # will return a dict without that field, and attrs will initialize the
    # model with the default value.
    if not attr_field.default is NOTHING:
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

    # Determine the key in JSON for this field.
    data_key = attr_field.metadata.get('camelcase', to_camel_case(attr_field.name))

    return field_type(
        data_key=data_key,
        required=required,
        **field_args
    )


def unmarshall_func(cls, input: Dict, *, use_server_fields):
    schema = cls.__marshmallow_schemas__['server' if use_server_fields else 'client']()
    schema.context = {
        'use_server_fields': use_server_fields
    }
    return schema.load(input)


def make_marshall_func(*, use_server_fields):
    def marshall_func(self):
        schema = self.__marshmallow_schemas__['server' if use_server_fields else 'client']()
        schema.context = {
            'use_server_fields': use_server_fields
        }
        return schema.dump(get_set_attrs(self))
    return  marshall_func


def get_schema_from_model_for_context(model_class, context):
    schema = model_class.__marshmallow_schemas__
    if context['use_server_fields']:
        return schema['server']
    return schema['client']


def marshallable(attrclass):
    """Adds `marshal`  and `unmarshal` classmethods to the attrs class to create the
    class from incoming unstructured data with validation.

    To this end, internally constructs a marshmallow schema based on the type
    definitions, and the attrs validators.
    """

    # If the class itself defines marshal/unmarshal methods, then the model in question
    # provides, in effect, a custom implementation; we set up a fake __marshmallow_schemas__
    # to wrap those methods. Other code will check for __marshmallow_schemas__ when it wants
    # to dump or load this module, so try to provide this interface.
    # NB: We do not use hasattr(), but check the dict directly, since we want such a class
    # to be subclassable; then, we do not want to find the marshal() method of the base class.
    if 'marshal' in attrclass.__dict__:
        manual_schema = make_manual_schema(attrclass, attrclass.marshal, attrclass.unmarshal)
        attrclass.__marshmallow_schemas__ = {
            'server': manual_schema,
            'client': manual_schema
        }
        return attrclass

    attr_fields = get_fields(attrclass)
    marshmallow_client_fields = {
        field.name: make_marshmallow_field(field)
        for field in attr_fields
        if not field.metadata.get('server_set')
    }
    marshmallow_server_fields = {
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

    def process_dumped_result(self, data, original):
        # Fields have the ability to provide a hook to customize how they are serialized.
        for field in get_fields(attrclass):
            marshal_helper = field.metadata.get('marshal', None)
            if marshal_helper:
                data = marshal_helper.marshal(data, original, field)
        return data

    for fieldset in (marshmallow_server_fields, marshmallow_client_fields):
        fieldset['_internal_make_object'] = post_load(make_object)
        fieldset['_internal_post_dump_object'] = post_dump(process_dumped_result, pass_original=True)

    marshmallow_client_schema = type(f'{attrclass}Schema', (marshmallow.Schema,), marshmallow_client_fields)
    marshmallow_server_schema = type(f'{attrclass}Schema', (marshmallow.Schema,), marshmallow_server_fields)

    attrclass.__marshmallow_schemas__ = {
        'server': marshmallow_server_schema,
        'client': marshmallow_client_schema,
    }

    attrclass.to_server = make_marshall_func(use_server_fields=False)
    attrclass.from_server = classmethod(partial(unmarshall_func, use_server_fields=True))
    attrclass.to_client = make_marshall_func(use_server_fields=True)
    attrclass.from_client = classmethod(partial(unmarshall_func, use_server_fields=False))

    return attrclass


def to_camel_case(snake_str):
    components = snake_str.split('_')
    # We capitalize the first letter of each component except the first one
    # with the 'title' method and join them together.
    result = components[0] + ''.join(x.title() for x in components[1:])

    if result.endswith('_'):  # To support "from_"
        result = result[:-1]
    return result


def snakecase(string):
    string = re.sub(r"[\-\.\s]", '_', str(string))
    if not string:
        return string
    result = string[0].lower() + re.sub(r"[A-Z]", lambda matched: '_' + matched.group(0).lower(), string[1:])

    if result in ('from',):
        result = result + '_'
    return result


class CustomNested(fields.Nested):
    """
    Like marshmallow's Nested, but two differences:

     - When serializing, when given a dict (rather than a model), just outputs the
       dict as given.

       We use this to allow developers to skip the model system and instead directly
       include the desired JMAP structures.

    - Second, it picks the right schema to use based on the context.
    """

    def __init__(self, nested, **kwargs):
        fields.Nested.__init__(self, None, **kwargs)
        self.nested_class = nested

    @property
    def nested(self):
        # We need to support string references ourselves here, since marshmallow itself
        # only deals in marshmallow schemas.
        if isinstance(self.nested_class, str):
            if self.nested_class == 'self':
                return self.parent.__class__
            else:
                raise ValueError('not yet supported')

        return get_schema_from_model_for_context(self.nested_class, self.parent.context)

    @nested.setter
    def nested(self, value):
        # Parent tries to do that
        pass


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


class CustomUnmarshalField(fields.Field):
    """
    If a model uses an attribute with a custom `unmarshal` function, then this field
    class is used, and it wraps the unmarshal helper. Only here, but not in the pre_load
    and post hooks marshmallow offers, are we able to consume multiple input fields.

    The other direction, serialization, is implemented differently - as a post_dump
    hook, because only there do we have the ability to marshal a single field into
    multiple output keys.

    This completely takes over processing, including missing/required handling. It is
    up to those methods to raise an error if the field is supposed to be required.
    You may return marshmallow.missing.
    """

    def __init__(self, **kwargs):
        self.unmarshal_func = kwargs.pop('unmarshal_func')
        self.attr_field = kwargs.pop('attr_field')
        super().__init__(**kwargs)

    def deserialize(self, value, attr=None, data=None, **kwargs):
        """
        By overriding `deserialize` instead of `_deserialize`, we skip the
        missing/required validation. That's ok - this is all the responsibility of
        the custom `unmarshal` function.
        """
        new_data, keys_used = self.unmarshal_func(data, self.attr_field)

        # We want a single field to be able to consume multiple keys in the input.
        # Marshmallow by default only removes the key that belongs to the field,
        # and does so after processing.
        #
        # We have to remove the keys that we consumed right now from the data
        # dict given to us, because we have no access to the logic inside
        # marshmallow which would do it at the end.
        #
        # It's a bit of a hack, because subsequent fields do not see the full
        # original data dictionary any more (since we modify it here), but it works
        # and seems to be one of a few bad options.
        if keys_used:
            for key in keys_used:
                del data[key]

        # Usually deserialize() calls this, which we replaced here.
        self._validate(new_data)

        return new_data


class EnumField(fields.Field):
    """
    Adapted from: https://github.com/justanr/marshmallow_enum/blob/master/marshmallow_enum/__init__.py
    """

    default_error_messages = {
        'by_name': 'Invalid enum member {input}',
        'by_value': 'Invalid enum value {input}',
        'must_be_string': 'Enum name must be string'
    }

    def __init__(self, enum, by_value=False, error='', *args, **kwargs):
        self.enum = enum
        self.by_value = by_value

        self.error = error

        super(EnumField, self).__init__(*args, **kwargs)

    def _serialize(self, value, attr, obj):
        if value is None:
            return None
        elif self.by_value:
            return value.value
        else:
            return value.name

    def _deserialize(self, value, attr, data):
        if value is None:
            return None
        elif self.by_value:
            return self._deserialize_by_value(value, attr, data)
        else:
            return self._deserialize_by_name(value, attr, data)

    def _deserialize_by_value(self, value, attr, data):
        try:
            return self.enum(value)
        except ValueError:
            self.fail('by_value', input=value, value=value)

    def _deserialize_by_name(self, value, attr, data):
        if not isinstance(value, (str)):
            self.fail('must_be_string', input=value, name=value)

        try:
            return getattr(self.enum, value)
        except AttributeError:
            self.fail('by_name', input=value, name=value)

    def fail(self, key, **kwargs):
        kwargs['values'] = ', '.join([str(mem.value) for mem in self.enum])
        kwargs['names'] = ', '.join([mem.name for mem in self.enum])

        if self.error:
            if self.by_value:
                kwargs['choices'] = kwargs['values']
            else:
                kwargs['choices'] = kwargs['names']
            msg = self.error.format(**kwargs)
            raise ValidationError(msg)
        else:
            super(EnumField, self).fail(key, **kwargs)


class PolyField(fields.Field):
    """
    Adapted from https://github.com/Bachmann1234/marshmallow-polyfield/blob/master/marshmallow_polyfield/polyfield.py

    However, ours should be smart enough to not need a manual decider function. Instead,
    it will check the following to make a decision as to which of the subtypes to parse:

    - The primitives associate with the type (int, str).
    - In case of a nested model, any key which is unique to that model.
    """

    def __init__(
        self,
        union_types: Dict[Any, Any],
        many=False,
        **metadata
    ):
        super(PolyField, self).__init__(**metadata)
        self.many = many
        self.union_types = union_types

    def _serialize(self, value, attr, obj, **kwargs):
        if not self.many:
            value = [value]

        results = []
        for v in value:
            # Figure out which type it is
            for pytype, field_class in self.union_types.items():
                if isinstance(v, pytype):
                    if hasattr(pytype, '__marshmallow_schemas__'):
                        # Indicates that we expect pytype to be a model
                        schema_class = get_schema_from_model_for_context(pytype, self.parent.context)
                        schema = schema_class()
                        schema.context.update(getattr(self, 'context', {}))
                        data = schema.dump(v)
                        results.append(data)

                    else:
                        results.append(field_class._serialize(v, attr, obj))
                    break
            else:
                raise ValidationError(f'Not a valid value for "{attr}": {v}')

        if self.many:
            return results
        else:
            return results[0]

    def _deserialize(self, value, attr, data, **kwargs):
        if not self.many:
            value = [value]

        results = []
        for v in value:
            found = False

            # See if any of the given types has a custom "pick me" helper.
            # This is an escape hatch to allow for the following JMAP scenario:
            #    `PolyField([str, HeaderFieldQuery])`
            # Here, both str and HeaderFieldQuery really expect a string, but we
            # should first ask HeaderFieldQuery if it can "parse" the string.
            for pytype in self.union_types:
                if hasattr(pytype, 'will_handle'):
                    if pytype.will_handle(v):
                        schema_class = get_schema_from_model_for_context(pytype, self.parent.context)
                        schema = schema_class()
                        schema.context.update(getattr(self, 'context', {}))
                        data = schema.load(v)
                        results.append(data)
                        continue

            # Figure out which type it is
            for pytype, field in self.union_types.items():
                # This only works with primitives
                if isinstance(v, pytype):
                    results.append(field._deserialize(v, attr, data))
                    found = True
                    break

            else:
                if isinstance(v, dict):
                    # See if we can recognize it by the keys
                    # Get all the schemas involved
                    schemas = [
                        get_schema_from_model_for_context(k, self.parent.context)
                        for k in self.union_types.keys()
                        if hasattr(k, '__marshmallow_schemas__')
                    ]

                    # Figure out those keys which are unique across all schemas
                    keys_for_schema = [set(s._declared_fields.keys()) for s in schemas]
                    counts = Counter([key for keys in keys_for_schema for key in keys])
                    unique_keys = set([k for k, v in counts.items() if v == 1])

                    # Test each schema
                    for schema_class, keys in zip(schemas, keys_for_schema):
                        for key in keys:
                            if key in unique_keys and key in v:
                                schema = schema_class()
                                schema.context.update(getattr(self, 'context', {}))
                                data = schema.load(v)
                                results.append(data)
                                found = True
                                break
                        if found:
                            break

            if not found:
                raise ValidationError(f'Not one of the possible valid types for "{attr}": {v}')

        if self.many:
            return results
        else:
            return results[0]


def make_manual_schema(attrclass, marshal_func, unmarshal_func):
    class ManualSchema(Schema):

        def dump(self, obj, many=None):
            return marshal_func(obj)

        def load(self, data, many=None, partial=None, unknown=None):
            return unmarshal_func(data)

    return ManualSchema

