import email.header
from datetime import datetime
from email.headerregistry import AddressHeader, DateHeader
from typing import Tuple, Any, Callable, Optional

from jmap.protocol.errors import JMapInvalidArguments
from jmap.protocol.models import HeaderFieldQuery, HeaderFieldForm, EmailAddress, MailboxRights, MailboxRole
from jmap.server.modules.models import make_mailbox_id, make_message_id, MailboxDataType, ImapMailbox


def decode_header(header_value: bytes, query: HeaderFieldQuery):
    """
    Decode the email header, and return in the requested form.
    """

    # Decode the bytes
    header_string = header_value.decode('utf-8')

    # Is the header empty?
    if not header_string.strip():
        header_string = ""
    else:
        # Cut off the header name
        header_string = header_string[header_string.index(':')+1:].lstrip()
        # Cut off the trailing CLRF
        header_string = header_string.rstrip('\r\n')

    if query.form == HeaderFieldForm.raw:
        return header_string

    if query.form == HeaderFieldForm.text:
        header = email.header.make_header(email.header.decode_header(header_string))
        return str(header)

    if query.form == HeaderFieldForm.addresses:
        # TODO: Validate headers where this form is disallowed by the spec.
        x = {}
        AddressHeader.parse(header_string, x)
        return [
            EmailAddress(email=f'{address.username}@{address.domain}', name=address.display_name)
            for group in x['groups'] for address in group.addresses
        ]

    if query.form == HeaderFieldForm.message_ids:
        return parse_message_ids(header_string)

    if query.form == HeaderFieldForm.date:
        x = {}
        DateHeader.parse(header_string, x)
        return x['datetime']

    if query.form == HeaderFieldForm.urls:
        # TODO: Complete
        return header_string

    raise ValueError("Allowed form, but unsupported by this server: {}".format(query.form))


def rewrite_convenience_prop_to_header_query(prop):
    """
    Rewrite the given property to a header query, as detailed in:

    https://jmap.io/spec-mail.html#properties-of-the-email-object

    If this is not one of the known convenience properties, return it unchanged.
    """
    if prop == 'message_id':
        return HeaderFieldQuery(name='message-id', form=HeaderFieldForm.message_ids)
    if prop == 'in_reply_to':
        return HeaderFieldQuery(name='in-reply-to', form=HeaderFieldForm.message_ids)
    if prop == 'references':
        return HeaderFieldQuery(name='references', form=HeaderFieldForm.message_ids)
    if prop == 'sender':
        return HeaderFieldQuery(name='sender', form=HeaderFieldForm.addresses)
    if prop == 'from_':
        return HeaderFieldQuery(name='from', form=HeaderFieldForm.addresses)
    if prop == 'to':
        return HeaderFieldQuery(name='to', form=HeaderFieldForm.addresses)
    if prop == 'cc':
        return HeaderFieldQuery(name='cc', form=HeaderFieldForm.addresses)
    if prop == 'bcc':
        return HeaderFieldQuery(name='bcc', form=HeaderFieldForm.addresses)
    if prop == 'reply_to':
        return HeaderFieldQuery(name='reply-to', form=HeaderFieldForm.addresses)
    if prop == 'subject':
        return HeaderFieldQuery(name='subject', form=HeaderFieldForm.text)
    if prop == 'sent_at':
        return HeaderFieldQuery(name='date', form=HeaderFieldForm.date)

    return prop


def resolve_email_property(prop):
    """
    Returns a 2-tuple: The imap property that we need to query to resolve
    this property, if any, and a "generator", that creates the value.
    """

    prop = rewrite_convenience_prop_to_header_query(prop)

    if prop == 'id':
        return None, lambda s, c: 1

    if prop == 'blob_id':
        return None, lambda s, c: 1

    if prop == 'mailbox_ids':
        return None, lambda s, c: {
            make_mailbox_id(c['message_id'].folderpath, c['message_id'].uidvalidity): True
        }

    if prop == 'keywords':
        return None, lambda s, c: {}

    if prop == 'received_at':
        return None, lambda s, c: datetime.utcnow() # XXX

    if prop == 'has_attachment':
        return None, lambda s, c: False

    if prop == 'preview':
        return None, lambda s, c: 'foo'

    if prop == 'body_values':
        return None, lambda s, c: {}

    if prop == 'text_body':
        return None, lambda s, c: ''

    if prop == 'html_body':
        return None, lambda s, c: ''

    if prop == 'attachments':
        return None, lambda s, c: []

    if prop == 'body_structure':
        return None, lambda s, c: None

    if prop == 'thread_id':
        return None, lambda s, c: make_message_id(
            c['message_id'].folderpath, c['message_id'].uidvalidity, c['message_id'].uid)

    if prop == 'size':
        return ('RFC822.SIZE', lambda s, c: s)  # XXX: is that the right size value?

    if isinstance(prop, HeaderFieldQuery):
        prop_name = prop.name.lower()
        return (f'BODY.PEEK[HEADER.FIELDS ({prop_name.upper()})]', lambda x, c: decode_header(x, prop))

    raise JMapInvalidArguments(f"Valid property, but this server does not implement it: {prop}")


def resolve_mailbox_property(property: str) -> Tuple[Optional[MailboxDataType], Callable]:
    if property == 'id':
        return None, lambda folder, info: folder.jmap_id

    if property == 'parent_id':
        return None, lambda folder, info: folder.jmap_id

    if property == 'total_emails':
        return MailboxDataType.needs_open, lambda folder, info: info.folder[b'EXISTS']

    if property == 'unread_emails':
        # \Recent in IMAP is different than \Seen. We really want the  latter, but
        # it is not available. \Recent might be close enough, though.
        return MailboxDataType.needs_open, lambda folder, info: info.folder[b'RECENT']

    # We simply have no good way to get this information, so we return 0
    if property == 'total_threads':
        return None, lambda *a: 0
    if property == 'unread_threads':
        return None, lambda *a: 0

    if property == 'sort_order':
        # IMAP does not support sort order
        return None, lambda *a: 0

    if property == 'role':
        return None, lambda folder, _: determine_mailbox_role(folder.flags)

    if property == 'my_rights':
        def get_my_rights(mailbox: ImapMailbox, info):
            # An implicit mailbox does not actually exist, so the user has no rights to it.
            if mailbox.implicit:
                return MailboxRights(
                    may_read_items=False,
                    may_add_items=False,
                    may_remove_items=False,
                    may_set_seen=False,
                    may_set_keywords=False,
                    may_create_child=False,
                    may_rename=False,
                    may_delete=False,
                    may_submit=False,
                )
            # None means ACLs are not supported by the server. We assume
            # the user has all rights.
            if not info.acls:
                return MailboxRights(
                    may_read_items=True,
                    may_add_items=True,
                    may_remove_items=True,
                    may_set_seen=True,
                    may_set_keywords=True,
                    may_create_child=True,
                    may_rename=True,
                    may_delete=True,
                    may_submit=True,
                )

            return MailboxRights(
                may_read_items=True,
                may_add_items=True,
                may_remove_items=True,
                may_set_seen=True,
                may_set_keywords=True,
                may_create_child=True,
                may_rename=True,
                may_delete=True,
                may_submit=True,
            )

        return MailboxDataType.needs_acl, get_my_rights

    raise JMapInvalidArguments(f"Valid property, but this server does not implement it: {prop}")


IMAP_ROLES_MAPPING = {
    b'\All': MailboxRole.All,
    b'\Archive': MailboxRole.Archive,
    b'\Drafts': MailboxRole.Drafts,
    b'\Flagged': MailboxRole.Flagged,
    b'\Junk': MailboxRole.Junk,
    b'\Sent': MailboxRole.Sent,
    b'\Trash': MailboxRole.Trash,
}


def determine_mailbox_role(flags: Tuple[bytes]) -> Optional[MailboxRole]:
    roles = [IMAP_ROLES_MAPPING[f] for f in flags if f in IMAP_ROLES_MAPPING]
    if roles:
        # An IMAP mailbox can have multiple rules, but in JMAP, only one.
        return roles[0]
    return None


def parse_message_ids(s):
    """
    It seems there is nothing in Python that does this, nor could I find could
    in the wild, so we have to do this ourselves.
    """

    parts = [p for p in [part.strip() for part in s.strip().split(' ')] if p]

    result = []
    for part in parts:
        if not part[0] == '<' and part[-1] == '<':
            return None  # parsing failed
        result.append(part[1:-1])

    return result