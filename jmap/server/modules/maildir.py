import mailbox

from jmap.protocol.mail import EmailModule
from jmap.protocol.models import MailboxGetArgs, MailboxGetResponse, Mailbox, EmailQueryArgs, EmailQueryResponse, \
    EmailGetArgs, EmailGetResponse


class MailboxEmailModule(EmailModule):
    """
    Works on top of the traditional mailbox format.
    """


class MboxModule(EmailModule):
    """This serves JMAP email from a particular mbox file.
    """

    def __init__(self, mbox_file, **kwargs):
        self.mbox = mailbox.mbox(mbox_file)
        super().__init__(**kwargs)

    def get_state_for(self, type: str):
        return len(self.mbox)

    def handle_mailbox_get(self, context, args: MailboxGetArgs):
        return MailboxGetResponse(
            account_id=args.account_id,
            state=self.get_state_for(Mailbox),
            list=[
                Mailbox(
                    id='default',
                    name="Mail",
                    role="inbox"
                )
            ],
            not_found=[]
        )

    def handle_email_query(self, context, args: EmailQueryArgs) -> EmailQueryResponse:
        EmailQueryResponse(
            account_id=args.account_id,
            collapse_threads=args.collapse_threads,
            query_state='none',
            position=0,
            ids=[],
            can_calculate_changes=False, # TODO: We probably can
        )

    def handle_email_get(self, context, args: EmailGetArgs) -> EmailGetResponse:
        pass