jmap-python
===========

This Python library intends to implement [JMAP](https://jmap.io) as a set of
generic primitives which are helpful in writing JMAP servers, as well as clients.

It's a work in progress, and far from complete, but is far enough along that you
might find it useful.


## Modules

In particular, it currently consists of the following parts:

1. It implements the JMAP data types as light-weight Python models, and supports
   serializing/deserializing them to and from JSON, including proper validation 
   according to the spec.
   
2. It provides an execution engine to process a JMAP request, including handling
   resolving JSON pointers and references to previous results.
      
3. It implements some of the controllers necessary for a server in a 
   [SansIO](https://github.com/brettcannon/sans-io) fashion, that is, without
   being based on any particular web framework. 
   
   Want to write a JMAP server using [Flask](http://flask.pocoo.org/)? Wrap the 
   generic request handlers provided by this library within Flask views.  


### Using the models

```python
from jmap.protocol.models import MailboxGetArgs, JMapRequest

# Parse the arguments a client might send for a `Mailbox/get` request: 
# https://jmap.io/spec-mail.html#mailbox/get
MailboxGetArgs.from_client({
    "account_id": 1,
    "ids": ["mailbox-1", "mailbox-2"]
})


# Parse a whole request structure:
JMapRequest.from_client({
    "using": [],
    "methodCalls": [["Core/echo", {"test": 42}, 1]]
})
```


### Handling a request

TBD: Show the executor system.


### Using the server views

TBD. The generic server helpers.