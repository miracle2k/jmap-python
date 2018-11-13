"""Objects representing the various data objects used in JMAP.

What we want from those objects:

1) The should be fun to use from Python, when building servers or clients,
   providing for some amount of validation to help the programmer achieve
   correctness.

2) We need to be able to take unstructured, untrusted data coming from clients,
   validate it, and convert it into those objects.

In addition:

3) We like to use snake_case internally, but the JMAP APIs use camelCase.
4) JMAP also has the concept of allowing properties to be selected, and requiring an
   error if a given property name is invalid, so the models help us there too, knowing
   which fields exist.

`marshmallow` is suboptimal for (1). `dataclasses` have limitation such
as subclassing. attrs allows us to use keyword-only arguments to avoid
subclassing issues, but both do not do well enough at validating input.
`pydantic` has a good idea validating with Python type annotations, but
has some warts, and it's models are not as nice as does of `attr`.

`attr` is pretty nice, it gives us:

- Very nice Python models.
- MyPy annotations.
- (Some) runtime validation (arguments itself and custom validators, but
  not types) - that is good enough for now.

What we really need in addition to that is validating incoming JSON
- see (2). What this really means is (on top of just calling
`Model(**data)`:

- Validating the types (`attr` does not do this).
- Also running the type validation that attrs does not do at runtime.
- Properly handling nested objects as well.
- Giving us validation error messages pointing to specific fields.

Some options I considered:

- `cattrs` - does not output proper validation error messages.
- `pydantic` - does not work with `attr` classes (dataclasses are suopported!).
  I am not sure about it coercing types (for example True becomes 'True' -
  see https://github.com/samuelcolvin/pydantic/issues/284)
  Do we want to follow the robustness principle (https://en.wikipedia.org/wiki/Robustness_principle)
  and do those kinds of coercions?

We could make `pydantic` make with `attr` by writing a custom version of `pydantic.create_model.`
But at this point, we might just as well create a marshmallow model, which is more powerful, and
has no trouble with things such as camelCase/snakeCase.

And that is what we build in the `marshal.py` model.


-------------

JMAP type guide:

String|null (default: null) ===>  Optional[str] = None
String|null                 ===>  Optional[str] = None    (see 3.4 "null is always the default")
String (default="")         ===>  str = ""

In our models, Optional[str] allows None, but the type attribute needs to given.

To give more information to an attribute, such as validation logic, write:

Optional[str] = attr.ib()

This is preferable to a custom MyString type, since the types itself are used for
MyPy, which it is supposed to be a true string.
"""

from datetime import datetime
import enum
from typing import Dict, Any, List, Optional, Union
import attr
from marshmallow import ValidationError

from jmap.protocol.core import JMapNotRequest
from jmap.protocol.marshal import marshallable, custom_marshal, snakecase, get_marshmallow_field_class_from_python_type, \
    make_marshmallow_field_from_python_type, to_camel_case

MAIL_URN = 'urn:ietf:params:jmap:mail'
CALENDARS_URN = 'urn:ietf:params:jmap:calendar'
CONTACTS_URN = 'urn:ietf:params:jmap:contacts'


def PositiveInt(default=None):
    """The PositiveInt type specified by JMAP.

    This is a `attr.ib` which defines a validator. Use like this:

        @model
        class Foo:
            bar: int = PositiveInt(default=42)

    That is, the MyPy type remains an `int`, but the model has a
    validation logic and a default.
    """
    def larger_than_0(self, attribute, value):
        if value is not None and value < 0:
            raise ValueError(f'{self.__class__.__name__}.{attribute.name} is a PositiveInt and must be >0, but was given: {value}')
    return attr.ib(validator=larger_than_0, default=default)


def ModelPropertyWithHeader(model, **kwargs):
    """A string type that is restricted to one of the property names of `model`.

    This is a `attr.ib` which defines a validator. Use like this:

        @model
        class Foo:
            properties: str = ModelProperty(SomeOtherModel)

    That is, the MyPy type remains an `int`, but the model has a
    validation logic and a default.
    """

    all_attrs = [a.name for a in attr.fields(model)]

    def valid_property(self, attribute, value):
        # This runs when instantiating a model, as well as on umarshal.
        for item in value:
            if item in all_attrs:
                continue

            if isinstance(item, HeaderFieldQuery):
                continue

            # Can we parse it has a HeaderFieldQuery?
            try:
                HeaderFieldQuery.unmarshal(item)
            except ValidationError:
                pass
            else:
                continue

            raise ValueError(f'{self.__class__.__name__}.{attribute.name} was given "{item}", which is not an allowed value: {all_attrs}')

    def marshal(data, instance, field):
        """This manually serializes the property to `data`. It:

        - Serializes `header:*` queries.
        - Converts properties to camcel case.
        """
        props = getattr(instance, field.name)

        result = []
        for item in props:
            if isinstance(item, HeaderFieldQuery):
                result.append(str(item))
            else:
                result.append(to_camel_case(item))

        data[field.name] = result
        return data

    def unmarshal(data, field):
        """This manually initializes the property, given incoming JSON. It:

        - Handles `header:*` queries.
        - Converts properties to snake case.

        TODO: Support many properly. TODO: It might be nicer to just provide a custom field implementation here
        for fields.String, which automatically reject non-string types.
        """
        data = data.get(field.name)

        result = []
        for item in data:
            if HeaderFieldQuery.will_handle(item):
                result.append(HeaderFieldQuery.unmarshal(item))
            else:
                result.append(snakecase(item))

        return result, []

    return attr.ib(
        validator=valid_property,
        metadata={
            'marshal': custom_marshal(marshal=marshal, unmarshal=unmarshal)
        },
        **kwargs
    )


model = lambda klass: marshallable(attr.s(auto_attribs=True, kw_only=True)(klass))


#### Flatten headers


class HeaderFieldForm(enum.Enum):
    """
    4.1.2 Header fields parsed forms (https://jmap.io/spec-mail.html#emails)
    """

    raw = 'Raw'
    text = 'Text'
    addresses = 'Addresses'
    grouped_addresses = 'GroupedAddresses'
    message_ids = 'MessageIds'
    date = 'Date'
    urls = 'Urls'


field = make_marshmallow_field_from_python_type(HeaderFieldForm)
HeaderFieldForm.parse = lambda x: field.deserialize(x)


@model
class HeaderFieldQuery:
    """
    In JMAP, header queries can be given as formatted strings in the form:

        header:from
        header:from:asRaw
        header:from:asAddresses:all
    """

    name: str
    form: Optional[HeaderFieldForm] = HeaderFieldForm.raw
    all: bool = False
    original: str = attr.ib(cmp=False, default=None)

    def __str__(self):
        if self.original:
            return self.original

        parts = [self.name]
        if self.form:
            parts.append(f'as{self.form.value}')
        if self.all:
            parts.append('all')
        return ':'.join(parts)

    @classmethod
    def will_handle(cls, value: Any):
        if not isinstance(value, str):
            return False
        return value.startswith("header:")

    @classmethod
    def unmarshal(cls, str, **kwargs):
        parts = str.split(":")
        if not parts.pop(0) == 'header':
            raise ValidationError(f'Not a valid header field query: {str}')

        name = parts.pop(0) if parts else None
        if not name:
            raise ValidationError(f'Not a valid header field query: {str}')

        form = HeaderFieldForm.raw
        all = False

        if parts:
            if parts[0].startswith('as'):
                form = parts.pop(0)[2:]
                form = HeaderFieldForm.parse(form)
        if parts:
            if parts[0] == 'all':
                all = True
        if parts:
            raise ValidationError(f'These parts of the header query are unrecognized: {parts} ')

        return cls(name=name, form=form, all=all, original=str, **kwargs)

    def marshal(self):
        return str(self)


@model
class QueriedHeaderField(HeaderFieldQuery):
    value: str

    @classmethod
    def load_with_value(cls, key, value):
        return super().unmarshal(key, value=value)

    def format_key(self):
        # Only the super method formats the key properly
        return super().marshal()


def flatten_headers(data, instance, field):
    """
    Job: serialize `field` however desired for `instance`, add to `data` (which is already serialized).
    """
    items = getattr(instance, field.name)
    if items:
        for item in items:
            data[f'header:{item.format_key()}'] = item.value
    return data


def unflatten_headers(data, field):
    """
    Job: serialize `field` however desired for `instance`, add to `data` (which is already serialized).
    """
    result = []
    to_remove = []
    for key, value in data.items():
        if key.startswith("header:"):
            result.append(QueriedHeaderField.load_with_value(key, value=value))
            to_remove.append(key)

    return result, to_remove


def FlattenedHeaderQueries(**kwargs):
    return attr.ib(
        metadata={
            'marshal': custom_marshal(marshal=flatten_headers, unmarshal=unflatten_headers)
        }
    )



###### Base models


@model
class Comparator:
    property: str
    is_ascending: bool = True
    collation: str = ''


@model
class Mailbox:
    id: str
    name: str
    parent_id: Optional[str] = None
    role: Optional[str]
    sort_order: int = PositiveInt(default=0)


@model
class Thread:
    """
    3. Threads (https://jmap.io/spec-mail.html#threads)
    """
    id: str
    email_ids: List [str]


@model
class Account:
    """
    See "2. The JMAP Session resource".
    """
    name: str
    is_personal: bool
    is_read_only: bool
    has_data_for: List[str]


@model
class StandardGetArgs:
    """
    "5.1 /get" (https://jmap.io/spec-core.html#/get)
    """
    account_id: str
    ids: Optional[List[str]] = None

    # Properties
    # properties: Optional[List[str]] = None


@model
class StandardGetResponse:
    """
    "5.1 /get" (https://jmap.io/spec-core.html#/get)
    """
    account_id: str
    state: str
    not_found: List[str]
    #list: List[*]


@model
class StandardQueryArgs:
    """
    "5.5 /query" (https://jmap.io/spec-core.html#/query)
    """

    account_id: str
    sort: Optional[List[Comparator]] = None
    position: int = 0
    anchor: Optional[str] = None
    anchor_offset: Optional[int] = None
    limit: Optional[int] = PositiveInt(default=None)
    calculate_total: bool = False

    # TODO: Subclasses need to define this to insert a concrecte type of
    # FilterCondition. I wonder if we can emply metaclasses to make StandardQueryArgs
    # more a template than a base class.
    # filter: Optional[dict] = None  # TODO


@model
class StandardQueryResponse:
    """
    "5.5 /query" (https://jmap.io/spec-core.html#/query)
    """
    account_id: str
    query_state: str
    can_calculate_changes: bool
    position: int = PositiveInt()
    total: Optional[int] = PositiveInt(default=None)
    ids: List[str]


####### Mailbox/get


@model
class MailboxGetArgs(StandardGetArgs):
    pass


@model
class MailboxGetResponse(StandardGetResponse):
    list: List[Mailbox]


####### Mailbox/query


@model
class MailboxQueryFilterCondition:
    """2.3 Filter Conditions (https://jmap.io/spec-mail.html#mailbox/query)."""
    parent_id: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    has_any_role: Optional[bool] = None
    is_subscribed: Optional[bool] = None


@model
class MailboxQueryArgs(StandardQueryArgs):
    pass


@model
class MailboxQueryResponse(StandardQueryResponse):
    pass


####### Email


@model
class EmailAddress:
    name: Optional[str] = None
    email: str


@model
class EmailHeader:
    name: str
    value: str


@model
class EmailBodyValue:
    value: str
    is_encoding_problem: bool = False
    is_truncated = False


@model
class EmailBodyPart:
    # 4.1.4 Body Parts
    part_id: Optional[str] = None
    blob_id: Optional[str] = None
    size: int = PositiveInt()
    headers: List[EmailHeader]
    name: Optional[str] = None
    type: str
    charset: Optional[str] = None
    disposition: Optional[str] = None
    cid: Optional[str] = None
    language: Optional[List[str]] = None
    location: Optional[str] = None
    sub_parts: Optional[List["self"]] = None

    # TODO: header: {header - field - name} #:asForm:all


@model
class Email:
    # https://jmap.io/spec-mail.html#properties-of-the-email-object
    # 4.1.1 Metadata
    id: str
    blob_id: str
    thread_id: str
    mailbox_ids: Dict[str, bool]
    keywords: Dict[str, bool] = attr.ib(default=attr.Factory(dict))
    size: int = PositiveInt()
    received_at: datetime

    # 4.1.3 Header fields properties
    headers: List[EmailHeader]

    # will have special serializtion support in both directions.
    #
    # 1. A client or server can specify the object (but no validation there)
    # 2. When dumping the structure, we flatten the fields
    # 3. When loading the fields, we unflatten them.
    header_fields: List[QueriedHeaderField] = FlattenedHeaderQueries()

    # This are shortcuts for particular header queries (also see 4.1.3).
    #
    # There is no special handling for those, these model properties are not linked
    # up with the header field. We need to be able to output only the one or the other,
    # or both, depending on what the user requested via JMAP.
    #
    # However, there are helpers for de-duplicating the shortcuts.
    message_id: Optional[List[str]] = None
    in_reply_to: Optional[List[str]] = None
    references: Optional[List[str]] = None
    sender: Optional[List[EmailAddress]] = None
    from_: Optional[List[EmailAddress]] = None
    to: Optional[List[EmailAddress]] = None
    cc: Optional[List[EmailAddress]] = None
    bcc: Optional[List[EmailAddress]] = None
    reply_to: Optional[List[EmailAddress]] = None
    subject: Optional[str] = None
    sent_at: Optional[datetime] = None

    # 4.1.4 Body Parts
    body_structure: EmailBodyPart
    body_values: Dict[str, EmailBodyValue]
    text_body: List[EmailBodyPart]
    html_body: List[EmailBodyPart]
    attachments: List[EmailBodyPart]
    has_attachment: bool
    preview: str


####### Email/get


def safe(x):
    if x == 'from':
        return f'{x}_'
    return x


DEFAULT_EMAIL_GET_PROPERTIES = list(map(lambda x: safe(snakecase(x)), [
    "id", "blobId", "threadId", "mailboxIds", "keywords", "size",
    "receivedAt", "messageId", "inReplyTo", "references", "sender", "from",
    "to", "cc", "bcc", "replyTo", "subject", "sentAt", "hasAttachment",
    "preview", "bodyValues", "textBody", "htmlBody", "attachments"
]))


@model
class EmailGetArgs(StandardGetArgs):
    properties: Optional[List[Union[str, HeaderFieldQuery]]] = \
        ModelPropertyWithHeader(Email, default=DEFAULT_EMAIL_GET_PROPERTIES)

    body_properties: Optional[List[str]] = None
    fetch_text_body_values: bool = False
    fetch_html_body_values: bool = False
    fetch_all_body_values: bool = False
    max_body_value_bytes: int = PositiveInt(default=0)


@model
class EmailGetResponse(StandardGetResponse):
    list: List[Email]


@model
class EmailGetResponse(StandardGetResponse):
    list: List[Email]


###### Email/query

@model
class EmailQueryFilterCondition:
    """4.4.1 Filtering (https://jmap.io/spec-mail.html#mailbox/query)."""
    in_mailbox: Optional[str] = None
    in_mailbox_other_than: Optional[List[str]] = None
    # before, after
    min_size: Optional[int] = PositiveInt(default=None)
    max_size: Optional[int] = PositiveInt(default=None)


@model
class EmailQueryArgs(StandardQueryArgs):
    """
    "4.4 /query" (https://jmap.io/spec-mail.html#email/query)
    """
    collapse_threads: bool = False

    # TODO: Must be a union with FilterOperator
    filter: Optional[EmailQueryFilterCondition] = attr.ib(default=attr.Factory(EmailQueryFilterCondition))


@model
class EmailQueryResponse(StandardQueryResponse):
    """
    "4.4 /query" (https://jmap.io/spec-mail.html#email/query)
    """
    collapse_threads: bool


###### Thread/get


@model
class ThreadGetArgs(StandardGetArgs):
    pass


@model
class ThreadGetResponse(StandardGetResponse):
    list: List[Thread]


###### Others

@attr.s(auto_attribs=True, kw_only=True)
class MethodCall:
    name: str
    args: Dict[str, Any]
    client_id: str


@attr.s(auto_attribs=True, kw_only=True)
class JMapRequest:
    using: List[str]
    method_calls: List[MethodCall]

    @staticmethod
    def from_json(data):
        # This is not mentioned in the spec directly, but the echo example (4.1)
        # suggests this kind of shortened message, and clients in the wild
        # (linagora/jmap-client) send this kind of response, so support it.
        if isinstance(data, list):
            methods = parse_methods(data)
            return JMapRequest(
                using=[],
                method_calls=methods
            )

        if isinstance(data, dict):
            methods = parse_methods(data.get('methodCalls'))
            return JMapRequest(
                using=data.get('using', []),
                method_calls=methods
            )

        raise ValueError("Invalid request: {}".format(data))


def parse_methods(data):
    methods = []
    for call in data:
        try:
            method_name, args, client_id = call
        except ValueError:
            raise JMapNotRequest()
        methods.append(MethodCall(name=method_name, args=args, client_id=client_id))
    return methods


@attr.s(auto_attribs=True, kw_only=True)
class JMapResponse:
    method_responses: List[Any]

    def to_json(self):
        return {
            'methodResponses': self.method_responses
        }


@model
class ResultReference:
    result_of: str
    name: str
    path: str
