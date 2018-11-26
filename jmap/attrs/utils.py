from jmap.attrs import attrs


class AsObject:
    def __init__(self, obj):
        self.obj = obj

    def __getattr__(self, item):
        try:
            return self.obj[item]
        except KeyError:
            raise AttributeError(item)


def get_set_attrs(instance):
    """
    Return only those attributes which have been set. We need
    to go into the slots here.
    """
    klass = instance.__class__

    if getattr(klass, '__slots__', None):
        values = {}
        for slot_name in klass.__slots__:
            if slot_name.startswith('__'):
                continue
            try:
                value = getattr(klass, slot_name).__get__(instance)
            except AttributeError as e:
                pass
            else:
                values[slot_name] = value
        return values

    else:
        # marshmallow can handle both, but our custom code should have a
        # common interface as well.
        return AsObject(instance.__dict__)


def properties(instance):
    return attrs.fields_dict(instance).keys()