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
from imaplib import IMAP4
from typing import Tuple, List, Dict, Optional

from imapclient.exceptions import CapabilityError

from jmap.protocol.errors import JMapInvalidArguments, JMapUnsupportedFilter, JmapCannotCalculateChanges, \
    SetErrorNotFound
from jmap.protocol.mail import EmailModule
from jmap.protocol.models import MailboxGetArgs, MailboxGetResponse, EmailQueryArgs, EmailQueryResponse, \
    EmailGetResponse, EmailGetArgs, MailboxQueryArgs, \
    MailboxQueryResponse, Mailbox, MailboxChangesArgs, MailboxChangesResponse, Email, ThreadGetArgs, \
    ThreadGetResponse, ThreadChangesArgs, ThreadChangesResponse, Thread, EmailSetArgs, EmailSetResponse, \
    MailboxSetResponse, MailboxSetArgs
from imapclient import IMAPClient

from jmap.server.modules.models import make_mailbox_id, decode_mailbox_id, safe_decode_mailbox_id, make_message_id, \
    decode_message_id, ImapMailbox, MailboxDataType, MailboxData
from jmap.server.modules.properties import resolve_email_property, resolve_mailbox_property


class ImapCachePolicy:
    def get_request_resolver_cache(self, account_id: str, client: IMAPClient):
        # Return a new one every time
        return ImapCache(client)


class ImapCache:
    def __init__(self, client: IMAPClient):
        self.client = client
        self.cache = {}

    def fetch_mailbox_info(self, mailbox: ImapMailbox, what: Optional[MailboxDataType]) -> Optional[MailboxData]:
        if not what:
            return None

        acls = folder = None

        if MailboxDataType.needs_acl in what:
            try:
                acls = self.client.getacl()
            except CapabilityError:
                acls = False

        if MailboxDataType.needs_open in what:
            folder = self.client.select_folder(mailbox.full_path, readonly=True)

        return MailboxData(acls=acls, folder=folder)


class ImapProxyModule(EmailModule):

    def __init__(self, host, username, password, port=None, ssl=True):
        super().__init__()
        self.client =  IMAPClient(host=host, port=port, ssl=ssl)
        self.client.login(username, password)
        self.cache_policy = ImapCachePolicy()

    def handle_mailbox_get(self, context, args: MailboxGetArgs):
        # Get all folders
        # TODO: We could possibly only query the ids given
        folders = self.client.list_folders()
        folders = parse_imap_mailboxes(folders)
        add_implicit_parent_folders(folders)

        cache = self.cache_policy.get_request_resolver_cache(args.account_id, self.client)

        mailboxes = []
        for mailbox in folders.values():
            jmap_id = mailbox.jmap_id
            if args.ids and not jmap_id in args.ids:
                continue

            collected = {}
            for prop in args.properties:
                needed, func = resolve_mailbox_property(prop)
                info = cache.fetch_mailbox_info(mailbox, needed)
                collected[prop] = func(mailbox, info)

            mailboxes.append(Mailbox.Properties(**collected))

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

        # TODO: if they ask for subscribed - we have to query only those...
        folders = self.client.list_folders()
        folders = parse_imap_mailboxes(folders)

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

    def handle_mailbox_set(self, context, args: MailboxSetArgs) -> MailboxSetResponse:
        # Handle all create instructions
        created = {}
        if args.create:
            for create_id, object in args.create.items():
                partial_mailbox: Mailbox = object

                if partial_mailbox.parent_id:
                    parent_folder_path, _ = decode_mailbox_id(partial_mailbox.parent_id)
                    new_folder_path = f'{parent_folder_path}.{partial_mailbox.name}'
                else:
                    parent_folder_path = None
                    new_folder_path = f'{partial_mailbox.name}'
                self.client.create_folder(new_folder_path)

                imap_folder = ImapMailbox(
                    flags=None, parent_path=parent_folder_path, full_path=new_folder_path,
                    separator=".", name=partial_mailbox.name
                )

                created[create_id] = imap_folder.to_jmap_mailbox()

        # Handle all update instructions
        updated = {}
        if args.update:
            for item_id, object in args.update.items():
                pass

        # Handle all destroy instructions
        destroyed = []
        not_destroyed = {}
        if args.destroy:
            for id_to_destroy in args.destroy:
                folder_path = safe_decode_mailbox_id(id_to_destroy)
                if not folder_path:
                    not_destroyed[id_to_destroy] = SetErrorNotFound()
                else:
                    # TODO: args.on_destroy_remove_messages
                    self.client.delete_folder(folder_path)
                    destroyed.append(id_to_destroy)

        return MailboxSetResponse(
            account_id=args.account_id,
            new_state='test',
            created=created,
            destroyed=destroyed,
            not_destroyed=not_destroyed
        )


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
            imap_field, _ = resolve_email_property(prop)
            if imap_field:
                imap_fields.add(imap_field)

        found_list = []
        for message_id in message_ids:
            self.client.select_folder(message_id.folderpath)
            # TODO: validate uidvalidity

            # Query IMAP
            if imap_fields:
                response = self.client.fetch([message_id.uid], imap_fields)
                msg = response[message_id.uid]
                print(msg)
            else:
                msg = {}

            # now generate the props
            props_out = {}
            for prop in args.properties:
                imap_field, getter = resolve_email_property(prop)
                fimap_field = imap_field.replace('.PEEK', '').encode('utf-8') if imap_field else None
                value = msg[fimap_field] if fimap_field else None

                context = {
                    'message_id': message_id,
                }
                props_out[str(prop)] = getter(value, context)

            if not 'id' in props_out:
                props_out['id'] = make_message_id(message_id.folderpath, message_id.uidvalidity, message_id.uid)
            found_list.append(Email.Properties(**props_out))

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

    def handle_email_set(self, context, args: EmailSetArgs) -> EmailSetResponse:
        print(args)
        return EmailSetResponse(
            account_id=args.account_id,
            new_state='test'
        )

    def handle_thread_get(self, context, args: ThreadGetArgs) -> ThreadGetResponse:
        """
        """
        if not args.ids:
            # TODO: Which error should be return?
            raise JMapUnsupportedFilter('You can only query for threads with specific ids')

        native_ids = [decode_message_id(id) for id in args.ids]

        threads = []

        # group by folder!
        for thread_id in native_ids:
            self.client.select_folder(thread_id.folderpath)
            message_ids = self.client.thread(criteria=['INTHREAD', 'REFS', 'UID', thread_id.uid])[0]

            # TODO: How to deal with the properties here??
            thread = Thread(
                id=make_message_id(thread_id.folderpath, thread_id.uidvalidity, thread_id.uid),
                email_ids=[make_message_id(thread_id.folderpath, thread_id.uidvalidity, m) for m in message_ids]
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


def parse_imap_mailboxes(folders: Tuple) -> Dict[str, ImapMailbox]:
    """
    Given a folder 3-tuple from imaplib, returns `Folder` instances.
    """

    result = {}
    for folder_tuple in folders:
        box = ImapMailbox.from_tuple(folder_tuple)
        result[box.jmap_id] = box
    return result


def add_implicit_parent_folders(mailboxes: Dict[str, ImapMailbox]):
    for box in list(mailboxes.values()):
        # There is an implicit parent here, add it
        if not box.parent_path:
            continue
        if not box.jmap_parent_id in mailboxes:
            box = ImapMailbox.from_tuple(([], box.separator, box.parent_path))
            mailboxes[box.jmap_id] = box
