"""
We wrap attrs. It is just flexible enough to support what we need.
"""

from . import attrs
from .marshal import marshallable


def attrib(*, server_set=False, **kwargs):
    our_args = {}
    if server_set:
        metadata = our_args.setdefault('metadata', {})
        metadata['server_set'] = True
        our_args['init'] = False

    return attrs.attrib(**kwargs, **our_args)


def model(maybe_cls):
    def wrap(cls):
        attr_class = attrs.attrs(
            # Using slots automatically gives us attribute-validation
            # on set, because no new attributes are allowed, in addition
            # to performance improvements when dealing with a lot of
            # email objects, for example.
            #
            # TODO: Renable slots. It currently breaks __init_subclass__
            # with type arguments.
            slots=False,

            auto_attribs=True,
            kw_only=True
        )(cls)

        # `attr_class` now has an `__init__` as we designed
        # it for client-side use. cls.properties is for the server.
        attr_class.Properties = make_properties_loader(attr_class)

        # Add the marshal helpers.
        attr_class = marshallable(attr_class)

        return attr_class

    if maybe_cls is None:
        return wrap
    else:
        return wrap(maybe_cls)


def make_properties_loader(cls):
    @classmethod
    def properties(self, **kwargs):
        instance = cls.__new__(cls)
        for key, value in kwargs.items():
            setattr(instance, key, value)
        # TODO: Run validations
        return instance
    return properties