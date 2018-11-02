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

from typing import Dict, Any, List, Optional
import attr
from jmap.protocol.marshal import marshallable


MAIL_URN = 'urn:ietf:params:jmap:mail'
CALENDARS_URN = 'urn:ietf:params:jmap:calendar'
CONTACTS_URN = 'urn:ietf:params:jmap:contacts'


def PositiveInt(default=None):
    def larger_than_0(self, attribute, value):
        if value is not None and value < 0:
            raise ValueError(f'{self.__class__.__name__}.{attribute.name} is a PositiveInt and must be >0, but was given: {value}')
    return attr.ib(validator=larger_than_0, default=default)


model = lambda klass: marshallable(attr.s(auto_attribs=True, kw_only=True)(klass))


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
class EmailHeader:
    pass


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
    # TODO sub_parts: Optional[List["EmailBodyPart"]] = None


@model
class Email:
    # 4.1.1 Metadata
    id: str
    blob_id: str
    threadId: str
    #TODO mailbox_ids: Dict[str, bool]
    #keywords: Dict[str, bool]
    size: int = PositiveInt()
    # TODO received_at

    # 4.1.2 Header fields parsed forms
    raw: str
    text: str


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
    properties: Optional[List[str]] = None


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
    filter: Optional[dict] = None  # TODO
    sort: Optional[List[Comparator]] = None
    position: int = 0
    anchor: Optional[str] = None
    anchor_offset: Optional[int] = None
    limit: Optional[int] = PositiveInt(default=None)
    calculate_total: bool = False


@model
class StandardQueryResponse:
    """
    "5.5 /query" (https://jmap.io/spec-core.html#/query)
    """
    account_id: str
    filter: Optional[dict] = None  # TODO
    query_state: str
    can_calculate_changes: bool
    position: int = PositiveInt()
    total: Optional[int] = PositiveInt(default=None)
    ids: List[str]


@model
class MailboxGetArgs(StandardGetArgs):
    pass


@model
class MailboxGetResponse(StandardGetResponse):
    list: List[Mailbox]


@model
class EmailGetArgs(StandardGetArgs):
    pass


@model
class EmailGetResponse(StandardGetResponse):
    list: List[Email]


@model
class ThreadGetArgs(StandardGetArgs):
    pass


@model
class ThreadGetResponse(StandardGetResponse):
    list: List[Thread]


@model
class EmailQueryArgs(StandardQueryArgs):
    """
    "4.4 /query" (https://jmap.io/spec-mail.html#email/query)
    """
    collapse_threads: bool = False


@model
class EmailQueryResponse(StandardQueryResponse):
    """
    "4.4 /query" (https://jmap.io/spec-mail.html#email/query)
    """
    collapse_threads: bool


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
        method_name, args, client_id = call
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