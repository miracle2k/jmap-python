"""
A base class for the mail spec (https://jmap.io/spec-mail.html). The actual
implementations need to be provided by a child class.

What this does is:

- It defines the methods that exists.
- It calls into the permission hooks.
"""

import functools
import types
from jmap.modules.core import JmapBaseModule
from jmap.models.models import MailboxGetArgs, EmailQueryArgs, EmailQueryResponse, EmailGetResponse, EmailGetArgs, \
    ThreadGetArgs, ThreadGetResponse, MailboxQueryArgs, MailboxQueryResponse, MailboxChangesArgs, \
    MailboxChangesResponse, ThreadChangesArgs, ThreadChangesResponse, EmailSetResponse, EmailSetArgs, MailboxSetArgs, \
    MailboxSetResponse


def check_get_perms(instance, auth_backend, typename, handler):
    @functools.wraps(handler)
    def wrapped(self, context, args):
        if auth_backend:
            if not auth_backend.can_read(context, 'Account', args.account_id):
                raise ValueError(f'You cannot access {args.account_id}')
            if not auth_backend.can_read(context, 'Mailbox', args.ids):
                raise ValueError(f'You cannot access {args.account_id}')
        return handler(context, args)

    # To make it an instancemethod again.
    wrapped = types.MethodType(wrapped, instance)
    return wrapped


class EmailModule(JmapBaseModule):

    def __init__(self, *, auth_backend=None, **kwargs):
        super().__init__(**kwargs)

        self.methods = {
            'Mailbox/get': check_get_perms(self, auth_backend, 'Mailbox', self.handle_mailbox_get),
            'Mailbox/changes': self.handle_mailbox_changes,
            'Mailbox/query': self.handle_mailbox_query,
            'Mailbox/set': self.handle_mailbox_set,
            'Email/get': self.handle_email_get,
            'Email/query': self.handle_email_query,
            'Email/set': self.handle_email_set,
            'Thread/get': self.handle_thread_get,
            'Thread/changes': self.handle_thread_changes,
        }

    def handle_mailbox_get(self, context, args: MailboxGetArgs):
        raise NotImplementedError()

    def handle_mailbox_query(self, context, args: MailboxQueryArgs) -> MailboxQueryResponse:
        raise NotImplementedError()

    def handle_mailbox_changes(self, context, args: MailboxChangesArgs) -> MailboxChangesResponse:
        raise NotImplementedError()

    def handle_mailbox_set(self, context, args: MailboxSetArgs) -> MailboxSetResponse:
        raise NotImplementedError()

    def handle_email_get(self, context, args: EmailGetArgs) -> EmailGetResponse:
        raise NotImplementedError()

    def handle_email_query(self, context, args: EmailQueryArgs) -> EmailQueryResponse:
        raise NotImplementedError()

    def handle_email_set(self, context, args: EmailSetArgs) -> EmailSetResponse:
        raise NotImplementedError()

    def handle_thread_get(self, context, args: ThreadGetArgs) -> ThreadGetResponse:
        raise NotImplementedError()

    def handle_thread_changes(self, context, args: ThreadChangesArgs) -> ThreadChangesResponse:
        raise NotImplementedError()