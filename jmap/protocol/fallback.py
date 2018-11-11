"""
Implement all the "old" methods (as are in use by jmap-client), and redirect
to tne new implementations?
"""

from jmap.protocol.core import JmapBaseModule
from jmap.protocol.models import MailboxGetArgs


class FallbackModule(JmapBaseModule):

    def __init__(self, email_module):
        super().__init__()

        self.email_module = email_module

        self.methods = {
            'getMailboxes': self.handle_get_mailboxes,
        }    

    def handle_get_mailboxes(self, context, args: MailboxGetArgs):
        return self.email_module.handle_mailbox_get(context, args)