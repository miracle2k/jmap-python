"""This implements a mail-module for jmap-python which proxies to an IMAP server,
without keeping a local copy of the emails. To do this, in acts in a manner fit
to be considered an "online IMAP client" as defined in RFC 1733.

Because the capabilities of the IMAP protocol are fairly limited, and many servers
are further limited by a lack of support for certain IMAP extensions, while the
JMAP spec requires us to provide a great number of features, this backend will
always be limited in the subset of the JMAP functionality it can provide. In certain
cases, we may bend the "no data storage" rule to temporarily cache certain information,
such as message id <-> thread mappings, to work around limitations in IMAP.

Implementation-wise we might want to look towards webmail backends (e.g. Roundcube),
or context.io (which seems to function as a proxy). However, note that these can limit
themselves to the features they choose, which is likely less than JMAP requires.

------
Issues
------

# Mailboxes

JMAP requires us to be able to:

- Query a particular folder by id.
- Describe the current mailbox list as a "state".

## The ID

There are no folder ids in IMAP, only the folder name/path, so we can only use that name
for the concept of a "mailbox id". The UIDVALIDITY is not suitable, because it is not
guaranteed to be unique (even if on some servers there is a good change that it would be).

The UIDVALIDITY flag of a folder is supposed to increase (and only increase) when the folder
changes identity (is replaced with a different folder by the same).

We could make the folder id a combination of path and UIDVALIDITY. However, this increases
the complexity: Accessing UIDVALIDITY in IMAP requires us to issue a separate "select"
command for each folder. However, the only difference would be that clients would not expect
a folder changed in this way to contain the emails that were previously known to be in the
folder. However, our messages themselves must already carry the folder UIDVALIDITY in their
id, because there are no globally-unique ids in IMAP either. In other words:

- We can never detect an IMAP folder being renamed; it would always be a new folder.
- If an IMAP folder is replaced, for can tell, but for our JMAP clients it is as if
  the folder is still the same, but has been cleared of all previous messages, and a new
  set of messages has been added to it.


# Messages

JMAP requires us to be able to:

- Query a particular message by id.

There are no global IDs in IMAP - they are folder-specific. There is the message-id in the
header of an email, but using this has issues, too:

- It's not clear how reliable it really is - there could be duplicates.
- There might be performance issues on some servers - the value might not be indexed.
- Because IMAP only allows us to search in a single folder at a time, it is difficult to
  answer a JMAP query for a particular message id - we would not know in which folder to
  look.

Rather, we use a 3-tuple (folderpath, folder-uidvalidity, message-uid) as an id for
individual messages. This means that in practice, messages are bound to their folder. When
moved to a different folder, they would be treated as a different email.

About UIDs in IMAP, see also: https://tools.ietf.org/html/rfc3501#section-2.3.1.1

# Threads

Three types of IMAP servers:

- Those that do not understand threads at all.
- Those that support the basic THREADS extension, in which case we can search
  for messages in a folder, and get them back grouped by thread.
- Dovecot, which supports the experimental INTHREAD search
  (https://tools.ietf.org/html/draft-ietf-morg-inthread-01) - but does not advertise
  it as a capability (see https://www.dovecot.org/doc/NEWS-1.2, v1.2.0 2009-07-01).
- GMail, which exposes some limited threading info.

This is also discussed here: https://stackoverflow.com/a/16862688/15677

We are asked here to return all the emails in a thread. Except for Dovecot then,
we cannot get this information via IMAP. The best we can do is keep the mapping
client-side.



Other useful links:
-------------------

https://wiki.mozilla.org/Thunderbird:IMAP_RFC_4551_Implementation
https://www.imapwiki.org/ClientImplementation
https://lwn.net/Articles/680722/ (use gmail ids where available)

The Nylas sync engine (https://github.com/nylas/sync-engine/blob/b91b94b9a0033be4199006eb234d270779a04443/inbox/crispin.py)
has some prior art regarding connection pools, for example.
"""


import base64
import json
import time
from email.headerregistry import AddressHeader, DateHeader
import email.header
from imaplib import IMAP4
from typing import Tuple
import attr

from jmap.protocol.core import JMapUnsupportedFilter, JmapCannotCalculateChanges, JMapInvalidArguments
from jmap.protocol.mail import EmailModule
from jmap.protocol.models import MailboxGetArgs, MailboxGetResponse, EmailQueryArgs, EmailQueryResponse, \
    EmailGetResponse, EmailGetArgs, HeaderFieldQuery, HeaderFieldForm, EmailAddress, MailboxQueryArgs, \
    MailboxQueryResponse, Mailbox, MailboxChangesArgs, MailboxChangesResponse, Email, ThreadGetArgs, \
    ThreadGetResponse, ThreadChangesArgs, ThreadChangesResponse, Thread
from imapclient import IMAPClient


class ImapProxyModule(EmailModule):

    def __init__(self, host, username, password):
        super().__init__()
        self.client =  IMAPClient(host=host)
        self.client.login(username, password)
        print(self.client.capabilities())

    def handle_mailbox_get(self, context, args: MailboxGetArgs):
        # Get all Folders
        # TODO: We could possibly only query the ids given
        folders = self.client.list_folders()
        folders = folders_with_parents(folders)

        mailboxes = []
        for (flags, separator, parent, fullname, basename) in folders:
            mbox_id = make_mailbox_id(fullname, '')

            if args.ids and not mbox_id in args.ids:
                continue

            # TODO: Return only the queried properties!
            mailboxes.append(Mailbox(
                id=mbox_id,
                name=basename,
                parent_id=make_mailbox_id(parent, ''),
                role=None
            ))

        return MailboxGetResponse(
            account_id=args.account_id,
            list=mailboxes,
            not_found=[],
            state=f'{time.time()}'
        )

    def handle_mailbox_query(self, context, args: MailboxQueryArgs):
        # Query all folders
        # TODO: Rather than handling all filter conditions in Python, we should move them
        # to the query itself where possible (say the parent_id).
        folders = self.client.list_folders()
        folders = folders_with_parents(folders)

        filtered = folders
        if args.filter:
            if args.filter.has_any_role:
                raise JMapUnsupportedFilter()

            if args.filter.is_subscribed:
                raise JMapUnsupportedFilter()

            if args.filter.role:
                raise JMapUnsupportedFilter()

            if args.filter.parent_id:
                filtered = filter(lambda x: make_mailbox_id(x[2], '') == args.filter.parent_id, filtered)

            if args.filter.name:
                filtered = filter(lambda x: args.filter.name in x[4], filtered)

        return MailboxQueryResponse(
            account_id=args.account_id,

            # I don't think we have any value to represent to us when the set of
            # mailboxes has changed. The set of UIDVALIDITY values comes close,
            # but we cannot rely on any one of them being unique.
            query_state=f'{time.time()}',

            # We do not really have a way to figure out which folders changed,
            # and certainly not the changes for a particular query.
            can_calculate_changes=False,

            # We could include the UIDVALIDITY, but we'd have to open each folder,
            # so let's not do that.
            ids=[make_mailbox_id(folder[3], '') for folder in filtered],
        )

    def handle_mailbox_set(self, context, args: MailboxGetArgs):
        raise JMapUnsupportedFilter()

    def handle_mailbox_changes(self, context, args: MailboxChangesArgs) -> MailboxChangesResponse:
        """
        IMAP does not really have a way to get folder changes.    
        """""
        raise JmapCannotCalculateChanges()

    # def handle_mailbox_query_changes(self):
    #     # cannotCalculateChanges

    # thread_get
    # thread_changes

    def handle_email_get(self, context, args: EmailGetArgs) -> EmailGetResponse:
        if not args.ids:
            # TODO: Which error should be return?
            raise JMapUnsupportedFilter()

        # TODO: split into folders
        message_ids = [decode_message_id(mid) for mid in args.ids]

        # Given a set of properties the client wants to query, figure out which properties
        # *we* have to request from the IMAP server. Some of the JMAP properties map
        # directly to an IMAP fetch field, others we can generate locally.
        imap_fields = set()
        for prop in args.properties:
            imap_field, _ = resolve_property(prop)
            if imap_field:
                imap_fields.add(imap_field)

        found_list = []
        for mesage_id in message_ids:
            self.client.select_folder(mesage_id.folderpath)
            # TODO: validate uidvalidity

            # Query IMAP
            if imap_fields:
                response = self.client.fetch([mesage_id.uid], imap_fields)
                msg = response[mesage_id.uid]
                print(msg)
            else:
                msg = {}

            # now generate the props
            props_out = {}
            for prop in args.properties:
                imap_field, getter = resolve_property(prop)
                fimap_field = imap_field.replace('.PEEK', '').encode('utf-8') if imap_field else None
                value = msg[fimap_field] if fimap_field else None

                context = {
                    'mesage_id': mesage_id
                }
                props_out[str(prop)] = getter(value, context)

            found_list.append(Email.properties(**props_out))

        return EmailGetResponse(
            account_id=args.account_id,
            state='test',
            not_found=[],
            list=found_list
        )

    def handle_email_query(self, context, args: EmailQueryArgs) -> EmailQueryResponse:
        if not args.filter.in_mailbox:
            raise JMapUnsupportedFilter("A search must be inside a single mailbox, specify in_mailbox.")

        if args.filter.in_mailbox_other_than:
            raise JMapUnsupportedFilter("in_mailbox_other_than is not supported")


        mailbox_id, mailbox_uidval = decode_mailbox_id(args.filter.in_mailbox)

        # Select the folder in question
        try:
            folder = self.client.select_folder(mailbox_id, readonly=True)
            # todo: compare uidvalidity
        except IMAP4.error:
            raise

        # If not other criterias are given, we might want to use list, because
        # it allows us to get an index.

        criteria = 'ALL'
        all_message_ids = self.client.search(criteria)

        # We cannot apply position/limit in a search query, so
        # we have unfortunately load the whole result and limit the query
        # in Python.
        message_ids = all_message_ids[args.position:args.limit]

        # IMAP message ids are only unique within a single mailbox. To get
        # a real, account-wide unique ids, we have to combine folders name,
        # folder UIDVALIDITY, and the actual message uid.
        message_ids = [
            make_message_id(mailbox_id, folder[b'UIDVALIDITY'], uid)
            for uid in message_ids
        ]

        return EmailQueryResponse(
            account_id=args.account_id,

            # Our options for the state are UIDNEXT or HIGHESTMODSEQ. Both are imperfect:
            # UIDNEXT does not change if one of the results is deleted, HIGHESTMODSEQ
            # does change when flags are update, which is not desired.
            #
            # We also add UIDVALIDITY in there, because it is not part of the folder id.
            # That is, from the JMAP view, folder is never change, even if a folder has
            # been replaced with a new copy. Instead, we invalidate the query state of
            # anything that involves the folder.
            query_state=make_email_state_string(folder[b'UIDNEXT'], folder[b'UIDVALIDITY']),

            # We might be able to do this with the right extensions.
            can_calculate_changes=False,

            # Not sure if we can support this.
            collapse_threads=args.collapse_threads,

            ids=message_ids,
            position=args.position,  # TODO: Calculate, if it was negative, or needs clamping
            total=len(message_ids) if args.calculate_total else None,  # TODO: Make sure it is missing, not None
        )

    def handle_email_changes(self, context, args: EmailQueryArgs) -> EmailQueryResponse:
        """
        # we can never return changes globally for all mailboxes
        """

    def handle_email_query_changes(self, context, args: EmailQueryArgs) -> EmailQueryResponse:
        """
        # we might be able to return changes, but only if the filter is a single mailbox
        """

    def handle_thread_get(self, context, args: ThreadGetArgs) -> ThreadGetResponse:
        """
        """
        if not args.ids:
            # TODO: Which error should be return?
            raise JMapUnsupportedFilter('You can only query for threads with specific ids')

        native_ids = [decode_message_id(id) for id in args.ids]

        threads = []

        # group by folder!
        for folderpath, uidvalidity, uid in native_ids:
            self.client.select_folder(folderpath)
            message_ids = self.client.thread(criteria=['INTHREAD', 'REFS', 'UID', uid])[0]

            # TODO: How to deal with the properties here??
            thread = Thread(
                id=make_message_id(folderpath, uidvalidity, uid),
                email_ids=[make_message_id(folderpath, uidvalidity, m) for m in message_ids]
            )
            threads.append(thread)

        return ThreadGetResponse(
            account_id=args.account_id,
            state='test',
            not_found=[],
            list=threads
        )

    def handle_thread_changes(self, context, args: ThreadChangesArgs) -> ThreadChangesResponse:
        """TODO: We can only possible support this by querying for mail changes, being then
        able to figure out the threads for each mail, seing if a thread is new or removed, or
        has been updated. Though one.
        """
        raise JMapInvalidArguments()


def make_email_state_string(uidnext, uidvalidity):
    data = json.dumps([uidnext, uidvalidity]).encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def make_mailbox_id(folder_path, uidvalidity):
    """Generate a folder id, based on the folder name and the folder's UIDVALIDITY.
    """
    data = json.dumps([folder_path, uidvalidity]).encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode('utf-8')


def decode_mailbox_id(mailbox_id: str) -> Tuple[str, str]:
    """Raises a ValueError if the id is not properly encoded.

    I suggest the caller treats this error as an id that was not found.
    """
    mailbox_id += "=" * (-len(mailbox_id) % 4)

    data = json.loads(base64.urlsafe_b64decode(mailbox_id))
    return data[0], data[1]


def make_message_id(folder_path, uidvalidity, message_uid):
    """Generate a message id, based on the folder name, the folder's UIDVALIDITY
    and the message id.
    """
    data = json.dumps([folder_path, uidvalidity, message_uid]).encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode('utf-8')


@attr.s(auto_attribs=True)
class ImapMesageId:
    folderpath: str
    uidvalidity: str
    uid: str


def decode_message_id(message_id: str) -> ImapMesageId:
    """Raises a ValueError if the id is not properly encoded.

    I suggest the caller treats this error as an id that was not found.
    """
    message_id += "=" * (-len(message_id) % 4)

    data = json.loads(base64.urlsafe_b64decode(message_id))
    return ImapMesageId(folderpath=data[0], uidvalidity=data[1], uid=data[2])


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

    raise ValueError("Unsupported form: {}".format(query.form))


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


def resolve_property(prop):
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
        return None, lambda s, c: {}

    if prop == 'keywords':
        return None, lambda s, c: {}

    if prop == 'received_at':
        return None, lambda s, c: None # XXX

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

    if prop == 'thread_id':
        return None, lambda s, c: make_message_id(
            c['message_id'].folderpath, c['message_id'].uidvalidity, c['message_id'].uid)

    if prop == 'size':
        return ('RFC822.SIZE', lambda s, c: s)  # XXX: is that the right size value?

    if isinstance(prop, HeaderFieldQuery):
        prop_name = prop.name.lower()
        return (f'BODY.PEEK[HEADER.FIELDS ({prop_name.upper()})]', lambda x, c: decode_header(x, prop))

    raise JMapInvalidArguments(f"Unknown property: {prop}")


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


def folders_with_parents(folders: Tuple):
    """
    Given a folder 3-tuple from imaplib, add parent paths.
    """

    with_parent = []
    for flags, sep, name in folders:
        parts = name.rsplit(sep.decode('utf-8'), 1)
        if len(parts) == 1:
            parent = ''
            base = parts[0]
        else:
            parent, base = parts
        with_parent.append((flags, sep, parent, name, base))

    return with_parent