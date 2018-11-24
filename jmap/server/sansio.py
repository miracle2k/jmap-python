from typing import Dict

from jmap.protocol.errors import JMapRequestError, JMapError
from jmap.protocol.executor import Executor
from jmap.protocol.models import JMapRequest


def handle_request_from_json(request_json: Dict) -> Dict:
    """Give a JMAP request structure, such as would be posted to the JMAP
    API endpoint.
    """
    try:
        jmap_request = JMapRequest.from_json(request_json)
    except JMapRequestError as exc:
        return exc.to_json()

    executor = Executor(modules=[CoreModule(), email_module, fallback])

    # should we check the account id now?
    # pick a client for the guy?

    try:
        jmap_response = executor.execute(jmap_request)
    except JMapError as exc:
        return exc.to_json()

    return jmap_response.to_json()



# - you usually create the server on every call; certainly, it is stateless
# - if you want to create it once, you can, if the modules support that.
#  - most modules would be written to support that.
# - the imap module gets the client for each account id

# 1.

email_module = ImapProxyModule(client=pool.get_client_for_account())


# 2.

mail_module = ImapProxyModule(client_getter)


