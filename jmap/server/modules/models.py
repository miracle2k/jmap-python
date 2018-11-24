import base64
import enum
import json
from typing import Tuple, Optional

from jmap.models.attrs import attrs, attrib
from jmap.protocol.models import Mailbox


class MailboxDataType(enum.IntFlag):
    needs_acl = enum.auto()
    needs_open = enum.auto()


@attrs(slots=True, kw_only=True)
class MailboxData:
    acls = attrib()
    folder = attrib()


def make_mailbox_id(folder_path, uidvalidity):
    """Generate a folder id, based on the folder name and the folder's UIDVALIDITY.
    """
    # Do not use uidvalidity at this point
    data = json.dumps([folder_path, '']).encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode('utf-8')


def decode_mailbox_id(mailbox_id: str) -> Tuple[str, str]:
    """Raises a ValueError if the id is not properly encoded.

    I suggest the caller treats this error as an id that was not found.
    """
    mailbox_id += "=" * (-len(mailbox_id) % 4)
    try:
        bytes = base64.urlsafe_b64decode(mailbox_id)
    except ValueError:
        raise

    try:
        string = bytes.decode('utf-8')
    except UnicodeDecodeError:
        raise   # Already a ValueError

    try:
        data = json.loads(string)
    except json.JSONDecodeError:
        raise   # A ValueError

    if not isinstance(data, list) and len(list) != 2:
        raise ValueError('Not the right JSON structure for a mailbox id')

    return data[0], data[1]


def safe_decode_mailbox_id(mailbox_id: str) -> Optional[Tuple[str, str]]:
    try:
        theid, _ = decode_mailbox_id(mailbox_id)
        return theid
    except ValueError:
        return None


def make_message_id(folder_path, uidvalidity, message_uid):
    """Generate a message id, based on the folder name, the folder's UIDVALIDITY
    and the message id.
    """
    data = json.dumps([folder_path, uidvalidity, message_uid]).encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode('utf-8')


@attrs(auto_attribs=True, slots=True)
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


@attrs(auto_attribs=True, slots=True, kw_only=True)
class ImapMailbox:
    flags: Optional[Tuple[str]] = None
    separator: str
    parent_path: str
    full_path: str
    name: str
    implicit: str = attrib(default=False)

    @classmethod
    def from_tuple(self, imap_tuple):
        flags, sep, name = imap_tuple
        parts = name.rsplit(sep.decode('utf-8'), 1)
        if len(parts) == 1:
            parent = ''
            base = parts[0]
        else:
            parent, base = parts

        return ImapMailbox(
            flags=flags,
            separator=sep,
            parent_path=parent,
            full_path=name,
            name=base
        )

    @property
    def jmap_id(self):
        return make_mailbox_id(self.full_path, "")

    @property
    def jmap_parent_id(self):
        return make_mailbox_id(self.parent_path, "")

    def to_jmap_mailbox(self):
        return Mailbox.Properties(
            id=self.jmap_id,
            name=self.name,
            parent_id=self.jmap_parent_id,
            role=None,
            is_subscribed=True
        )