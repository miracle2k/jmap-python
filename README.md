jmap-python
===========

Currently, just a JMAP playground for myself.

Might become:

- A server implementation with pluggable backends.
- A proxy implementation.
- Maybe a client library.


Start a server:

    $ python -m jmap

Echo call:

    $ http GET localhost:5000/.well-known/jmap
    $ http POST localhost:5000/ using="" methodCalls:=' [[ "Core/echo", {"test": 5}, 1]]  '
    $ http POST localhost:5000/ using="" methodCalls:=' [[ "Email/query", {"accountId": "1", "filter": {"inMailbox": "inbox"}, "limit": 2}, 1]]  '

