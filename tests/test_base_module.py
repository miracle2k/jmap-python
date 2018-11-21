import pytest

from jmap.protocol.errors import JMapInvalidArguments
from jmap.protocol.mail import EmailModule
from jmap.protocol.models import MailboxGetArgs
from jmap.server.accounts import StaticBackend


def test_email():

    class Module(EmailModule):
        def handle_mailbox_get(self, context, args: MailboxGetArgs):
            assert args.account_id == 'test'
            return {}

    with pytest.raises(JMapInvalidArguments):
        Module().execute('Mailbox/get', {})

    Module(auth_backend=StaticBackend(accounts={})).execute('Mailbox/get', {'accountId': 'test'})
