import json
from jmap.protocol.models import MailboxGetArgs, MailboxGetResponse, Mailbox
from jmap.server import CustomJSONEncoder


def test_mailbox_get_args():
    mailbox = MailboxGetArgs(account_id=3)


def test_mailbox_get_response():
    response = MailboxGetResponse(
        account_id='foo',
        state='123',
        list=[
            Mailbox(
                id='default',
                name="Mail",
                role="inbox"
            )
        ],
        not_found=[]
    )

    print(CustomJSONEncoder().encode(response))