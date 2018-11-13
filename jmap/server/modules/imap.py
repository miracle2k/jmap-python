import base64
import json
from email.headerregistry import AddressHeader, DateHeader
import email.header
from imaplib import IMAP4
from typing import Tuple

from jmap.protocol.core import JMapUnsupportedFilter
from jmap.protocol.mail import EmailModule
from jmap.protocol.models import MailboxGetArgs, MailboxGetResponse, EmailQueryArgs, EmailQueryResponse, \
    EmailGetResponse, EmailGetArgs, HeaderFieldQuery, HeaderFieldForm, EmailAddress
from imapclient import IMAPClient


class ImapProxyModule(EmailModule):
    """Goals:

    1. Try to implement as much as possible without a local cache. Prior art
       here are things like Roundcube or other webmail server backends. context.io
       also seems to have no local cache.

    2. A version that supports a local cache. Nylas does it like this, as does the
       jmap-perl proxy.

    A server which supports all the features should be able to be just pass-through
    (QRESYNC - https://tools.ietf.org/html/rfc7162, even threads can be supported -
    https://tools.ietf.org/html/rfc5256), but lacking this, what are our options?

    Links:

    https://wiki.mozilla.org/Thunderbird:IMAP_RFC_4551_Implementation
    https://www.imapwiki.org/ClientImplementation
    https://lwn.net/Articles/680722/
        use gmail ids where available

    Definitely have a look at:
        https://github.com/nylas/sync-engine/blob/b91b94b9a0033be4199006eb234d270779a04443/inbox/crispin.py
    for some previous art.

    TODO:
    - cannotCalculateChanges
    """

    def __init__(self, host, username, password):
        super().__init__()
        self.client =  IMAPClient(host=host)
        self.client.login(username, password)
        print(self.client.capabilities())

    def handle_mailbox_get(self, context, args: MailboxGetArgs):
        """There are no folder ids in IMAP.

        Folders are identified by name, only. The UIDVALIDITY flag of a folder is supposed
        to increase (and only incraese) when the folder changes identity (is replaced with 
        a different folder by the same), and implemeentation-wise, if a folder is renamed, 
        it is likely to remain stable, and dovecot for example uses the folder creation 
        timestamp, so there may very  well be no two folders with the same UIDVALIDITY. 
        However, the last two things are not guaranteed, and so, we cannot use this flag 
        for an id. Can it be used for state? 

        Also of note: Accessing UIDVALIDITY requires us to inspect each folder individually.

        The UIDNEXT field we can trust will go only up and will only change if there are new
        messages, or if the folder is reset via UIDVALIDITY. Since it can be reset, I am
        not sure if can serve as a `state`.        

        What would a proper folder id help us with anyway here?; it's not enoough to implement
        the /changes resource, certainly.

        (also see https://tools.ietf.org/html/rfc3501#section-2.3.1.1)
        """

        # Get all Folders
        # we could possibly only query the ids given
        folders = self.client.list_folders()

        # group them by parents
        mailboxes = []
        for (flags, separator, name) in folders:
            mailboxes.append(Mailbox(
                # Should we attach the UUIDValidity to the id?
                id=name,
                name=name,
                parent_id=None

            ))

        return MailboxGetResponse(
            account_id=args.account_id
        )

    def handle_mailbox_query(self, context, args: MailboxGetArgs):        
        folders = self.client.list_folders()
        print(folders)
        # filter that shit
        # we could possible limit the list_folder()

    def handle_mailbox_set(self, context, args: MailboxGetArgs):
        # self.cache[context.userid, args.account_id]
        #
        # how do we get the connection data? can be a pool as well!
        # self.get_client(
        folders = self.client.list_folders()
        print(folders)

    # def handle_mailbox_changes(self):
    #     # cannotCalculateChanges

    # def handle_mailbox_query_changes(self):
    #     # cannotCalculateChanges

    # thread_get
    # thread_changes

    # (folder name, folder UIDVALIDITY, message UID)
    # Other ideas do not work either: sequence ids can easily change in each session, 
    #     message-ids may not exist and might not be trustworthy (there could be dups), nor 
    #     can be query an IMAP server with them.

    def handle_email_get(self, context, args: EmailGetArgs) -> EmailGetResponse:
        if not args.ids:
            # TODO: Which error should be return?
            raise JMapUnsupportedFilter()

        # TODO: split into folders
        query = [decode_message_id(mid) for mid in args.ids]

        # Given a set of properties the client wants to query, figure out which properties
        # *we* have to request from the IMAP server. Some of the JMAP properties map
        # directly to an IMAP fetch field, others we can generate locally.
        imap_fields = set()
        for prop in args.properties:
            imap_field, _ = resolve_property(prop)
            if imap_field:
                imap_fields.add(imap_field)

        found_list = []
        for item in query:
            folderpath, uidvalidity, message_uid = item
            self.client.select_folder(folderpath)
            # TODO: validate uidvalidity
            response = self.client.fetch([message_uid], imap_fields)
            msg = response[message_uid]
            print(msg)

            # now generate the props
            props_out = {}
            for prop in args.properties:
                imap_field, getter = resolve_property(prop)
                fimap_field = imap_field.replace('.PEEK', '').encode('utf-8') if imap_field else None
                value = msg[fimap_field] if fimap_field else None

                props_out[str(prop)] = getter(value)

            found_list.append(props_out)

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

        # Select the folder in question

        try:
            folder = self.client.select_folder(args.filter.in_mailbox, readonly=True)
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
            make_message_id(args.filter.in_mailbox, folder[b'UIDVALIDITY'], uid)
            for uid in message_ids
        ]

        return EmailQueryResponse(
            account_id=args.account_id,
            # Our options for the state are UIDNEXT or HIGHESTMODSEQ. Both are imperfect:
            # UIDNEXT does not change if one of the results is deleted, HIGHESTMODSEQ
            # does change when flags are update, which is not desired.
            query_state=str(folder[b'UIDNEXT']),
            # We *might* be able to do this by idling, then applying the filter ourselves
            can_calculate_changes=False,
            # Not sure if we can support this.
            collapse_threads=args.collapse_threads,
            ids=message_ids,
            position=args.position,  # TODO: Calculate, if it was negative, or needs clamping
            total=len(message_ids) if args.calculate_total else None,  # TODO: Make sure it is missing, not None
        )


def make_message_id(folder_path, uidvalidity, message_uid):
    """Generate a message id, based on the folder name, the folder's UIDVALIDITY
    and the message id.
    """
    data = json.dumps([folder_path, uidvalidity, message_uid]).encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def decode_message_id(message_id: str) -> Tuple[str, str, str]:
    """Raises a ValueError if the id is not properly encoded.

    I suggest the caller treats this error as an id that was not found.
    """
    message_id += "=" * (-len(message_id) % 4)

    data = json.loads(base64.urlsafe_b64decode(message_id))
    return data[0], data[1], data[2]


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

    if prop == 'size':
        return ('RFC822.SIZE', lambda s: s)  # XXX: is that the right size value?

    if isinstance(prop, HeaderFieldQuery):
        prop_name = prop.name.lower()
        if prop_name == 'subject':
            return ('BODY.PEEK[HEADER.FIELDS (SUBJECT)]', lambda x: decode_header(x, prop))

        if prop_name == 'from':
            return ('BODY.PEEK[HEADER.FIELDS (FROM)]', lambda x: decode_header(x, prop))

        if prop_name == 'message-id':
            return ('BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]', lambda x: decode_header(x, prop))

        if prop_name == 'date':
            return ('BODY.PEEK[HEADER.FIELDS (DATE)]', lambda x: decode_header(x, prop))

        return (f'BODY.PEEK[HEADER.FIELDS ({prop_name.upper()})]', lambda x: decode_header(x, prop))

    raise ValueError(prop)


def parse_message_ids(s):
    """
    It seems there is nothing in Python that does this, nor could I find could
    in the wild, so we have to do this ourselves.
    """

    parts = [part.strip() for part in s.strip().split(' ')]

    result = []
    for part in parts:
        if not part[0] == '<' and part[-1] == '<':
            return None  # parsing failed
        result.append(part[1:-1])

    return result