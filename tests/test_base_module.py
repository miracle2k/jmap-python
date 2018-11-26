import pytest

from jmap.models.errors import JMapInvalidArguments
from jmap.modules.mail import EmailModule
from jmap.models.models import MailboxGetArgs
from jmap.server.accounts import SingleUser


def test_email():

    class Module(EmailModule):
        def handle_mailbox_get(self, context, args: MailboxGetArgs):
            assert args.account_id == 'test'
            return {}

    with pytest.raises(JMapInvalidArguments):
        Module().execute('Mailbox/get', {})

    Module(auth_backend=SingleUser(accounts={})).execute('Mailbox/get', {'accountId': 'test'})
