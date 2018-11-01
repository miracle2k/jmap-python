from jmap.protocol.mail import EmailModule
from jmap.protocol.models import MailboxGetArgs


class ImapProxyModule(EmailModule):
    """
    We got to redirect all requests
    """

    def handle_mailbox_get(self, context, args: MailboxGetArgs):
        # self.cache[context.userid, args.account_id]
        #
        # how do we get the connection data? can be a pool as well!
        # self.get_client(
        pass