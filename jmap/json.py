from json import JSONEncoder
from jmap.attrs import attrs


class JmapJSONEncoder(JSONEncoder):

    def default(self, obj):
        if attrs.has(type(obj)):
            if getattr(obj, 'to_client'):
                return obj.to_client()
            return attrs.asdict(obj)
        return JSONEncoder.default(self, obj)


