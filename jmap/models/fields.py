import datetime
from marshmallow import fields
from jmap.models import rfc3339


def serialize_rfc3339(date, localtime=True):
    """
    `localtime` - marshmallow intends this to mean:

        If not set, convert any timezone to UTC, or treat as UTC if naive,
        then output a string in UTC.

        If set, treat a naive datetime as UTC, but accept a tz-aware timezone
        as is, then output a string that gives the timezone used.
    """

    is_utc = (date.utcoffset() is None) or (date.utcoffset() == rfc3339.ZERO)

    # If this is a non-utc date and we are asked to render it in UTC, convert it
    if not localtime and not is_utc:
        date = date.astimezone(datetime.timezone.utc)

    # Remove the fractions
    date = date.replace(microsecond=0)

    # Just print the string
    return rfc3339.datetimetostr(date)


def deserialize_rfc3339(date):
    return rfc3339.parse_datetime(date)


class JmapDateTime(fields.DateTime):
    """
    JMAP requires a particular datetime format: RFC 3339 without fractional
    seconds. By default, marshmallow generates the wrong format.

    Most of JMAP uses their `UTCDate` type, as it should, but the spec does
    define a `Date` type which is allowed to have an offset.

    Currently, we do like this: We only ever output UTC dates.
    We parse whatever we get and give back a tz-aware datetime object.
    """

    SERIALIZATION_FUNCS = {
        **fields.DateTime.SERIALIZATION_FUNCS,
        'jmap-rfc3339': serialize_rfc3339
    }

    DESERIALIZATION_FUNCS = {
        **fields.DateTime.DESERIALIZATION_FUNCS,
        'jmap-rfc3339': deserialize_rfc3339
    }

    DEFAULT_FORMAT = 'jmap-rfc3339'

    localtime = False