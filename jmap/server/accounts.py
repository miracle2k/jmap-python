"""
Different backends to get accounts from.
"""

from typing import Dict
from jmap.models.models import Account


class AccountBackend:
    """This abstracts the way we can get the accounts available
    for a particular request context.

    We also put permission checks in there (TODO: Might be a different structure instead).
    """

    def get_accounts_for(self, context) -> Dict[str, Account]:
        raise NotImplementedError()

    def can_read(self, context, objecttype, objectid):
        # Deny by default
        return False


class SingleUser(AccountBackend):
    """
    A static list of accounts. Permission is always granted.
    """

    def __init__(self, accounts: Dict[str, Account]):
        self.accounts = accounts

    def get_accounts_for(self, context) -> Dict[str, Account]:
        return self.accounts

    def can_read(self, context, objecttype, objectid):
        return True


class TomlBackend(AccountBackend):
    """
    [account=foo]
    imap_host=1
    """

    def __init__(self, accounts: Dict[str, Account]):
        self.accounts = accounts

    def get_accounts_for(self, context) -> Dict[str, Account]:
        return self.accounts

    def can_read(self, context, objecttype, objectid):
        return True

