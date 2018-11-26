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
