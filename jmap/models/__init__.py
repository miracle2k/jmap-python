"""This is a model system which we use for the JMAP data types.

Here is what we need from it
----------------------------

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

For this, we use `attrs` combined with `marshmallow`.


Here is why we chose this option
--------------------------------

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

What we really need in addition to that is validating incoming JSON - see (2).
What this really means is (on top of just calling `Model(**data)`:

- Validating the types (`attr` does not do this).
- Also running the type validation that attrs does not do at runtime.
- Properly handling nested objects as well.
- Giving us validation error messages pointing to specific fields.

Some options I considered:

- `cattrs` - does not output proper validation error messages.
- `pydantic` - does not work with `attr` classes (dataclasses are supported!).
  I am not sure about it coercing types (for example True becomes 'True' -
  see https://github.com/samuelcolvin/pydantic/issues/284)
  Do we want to follow the robustness principle (https://en.wikipedia.org/wiki/Robustness_principle)
  and do those kinds of coercions?

We could make `pydantic` make with `attr` by writing a custom version of `pydantic.create_model.`
But at this point, we might just as well create a marshmallow model, which is more powerful, and
has no trouble with things such as camelCase/snakeCase.


However, we use our own patched copy of `attrs`
-----------------------------------------------

This is a similar system to `attrs` - an easy way to create Python
data classes by just giving the type annotations. Like `attrs`, it allows
us to deal with the following requirements:

- We can define all the JMAP data structures tersely, without much boilerplate.

- The resulting classes have a great DX both when implementing clients and
  servers, because they support all the Python features you expect.

However, we do not use `attrs`, because we need more:

In JMAP, certain models have different requirements as to what properties
are required, and which properties are allowed, depending on the situation.
For example:

- When calling `/set`, the object MUST NOT include any server-set values.
  This means the model used on the client must be different than the one
  one the server.

- The properties: we are only allowed to set the keys the client requested.

We thus need to be able to only serialize a specific set of properties only.
This turns out to be difficult: Default behaviour would make marshmallow output
all properties as part of serialization which are set in the source model.
And since in attrs, all properties are always set (either by the user or to
their defaults), all properties are always output. This is, however, not
always what we want:

1 Sometimes the JMAP spec dictates that a server response not contain
  a certain property - for example, the "total" property of a `/query`
  response when the total was not requested. This happens infrequently,
  and otherwise it is expected that the server returns full response
  objects, but it does happen.

2 When requesting a JMAP entity via `/get`, the properties wanted can
  be listed. It is desirable for us to only serialize back those properties
  which where requested, and not include any non-requested default values;
  especially when those defaults might actually be incorrect, and the real
  value is different (but was not read for performance reasons).

3 Similarly, the client, when sending a request, would prefer to only
  send the fields set by the user, and let the server let the missing ones
  fall to their default values, as opposed to the client itself sending
  a full object with everything the user did not specify set to a default.

Our custom version of `attrs` enables the desired features.
"""


from .wrap import model, attrib
from .attrs import Factory, fields