from typing import List

import pytest
from jmap.models.wrap import model, attrib


def test_cannot_set_server_set_props_on_client():
    """
    CLIENT-SIDE USE:

    `Mailbox(id=1)` does not work if `id`  is a server attribute.
    """
    @model
    class Mailbox:
        id: str = attrib(server_set=True)

    with pytest.raises(TypeError):
        Mailbox(id=1)

    # Even if there is a default
    @model
    class User:
        is_blocked: str = attrib(server_set=True, default=False)

    with pytest.raises(TypeError):
        User(is_blocked=True)

    # It is possible to set the attribute later on, since we do not
    # really make a distinction between the model being used client
    # or server-side. We don't want to overcomplicate.
    user = User()
    user.is_blocked = True

    # But when we marshal in client-mode, the attribute is excluded
    assert user.to_server() == {}


def test_default_props_are_not_serialized():
    """
    CLIENT-SIDE USE, SERVER-SIDE USE:

    `Mailbox.role` is not serialized if it has an implicit default.
    """
    @model
    class Mailbox:
        role: str = attrib(default='inbox')

    # We can access the attribute and get the default
    assert Mailbox().role == 'inbox'

    # But, because it was never explicitly set, it is not serialized.
    assert Mailbox().to_client() == {}
    assert Mailbox().to_server() == {}

    # If we do set it, then it *is* serialized
    assert Mailbox(role='foo').to_server() == {'role': 'foo'}

    # You can also assign the attribute later
    m = Mailbox()
    m.role = 'foo'
    assert m.to_client() == {'role': 'foo'}
    assert m.to_server() == {'role': 'foo'}

    # This remains true, even if we use a list [regression]
    @model
    class Parent:
        box: List[Mailbox]

    assert Parent(box=[Mailbox()]).to_client() == {'box': [{}]}


def test_can_initialize_without_required_properties():
    """
    SERVER-SIDE USE:

    `Mailbox.Properties()` can be used even if required properties are missing.
    """
    @model
    class Mailbox:
        id: str = attrib()
        name: str = attrib()

    # The default constructor requires those attributes
    with pytest.raises(TypeError):
        mailbox = Mailbox()

    # But, the special `properties` constructor does not!
    mailbox = Mailbox.Properties(id='1')

    # The properties that we skipped are not serialized
    assert mailbox.to_client() == {'id': '1'}
    assert mailbox.to_server() == {'id': '1'}


def test_can_initialize_with_server_side_properties():
    """
    SERVER-SIDE USE:

    `Mailbox.Properties()` can be used to set server-side properties.
    """
    @model
    class Mailbox:
        id: str = attrib(server_set=True)

    # The default does not allow those attributes to be set
    with pytest.raises(TypeError):
        mailbox = Mailbox(id=1)

    # But, the special `properties` constructor does!
    mailbox = Mailbox.Properties(id='1')
    # So on serialization, out us set
    assert mailbox.to_client() == {'id': '1'}
