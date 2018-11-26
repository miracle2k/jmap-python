from typing import Dict
from jmap.models.errors import JMapRequestError, JMapError
from jmap.models.executor import Executor
from jmap.models.models import JMapRequest


SESSION_URL_PATH = '/.well-known/jmap'


class Server:
    def __init__(self, *, modules, api_url, auth_backend):
        self.modules = modules
        self.api_url = api_url
        self.auth_backend = auth_backend

    def get_session_response(self, context):
        accounts = self.auth_backend.get_accounts_for(context)

        return {
            # We can get all of this from the context
            "username": 'user@domain.com',
            "primaryAccounts": {},
            "accounts": {
                account_id: account.marshal()
                for account_id, account in accounts.items()
            },
            "state": None,

            # This stuff was passed in the constructor
            "capabilities": {},
            "apiUrl": self.api_url,
            "uploadUrl": '/upload',
            "downloadUrl": '/download',
            "eventSourceUrl": '/events',
        }

    def handle_request_from_json(self, request_json: Dict, *, context) -> Dict:
        """Give a JMAP request structure, such as would be posted to the JMAP
        API endpoint.
        """
        try:
            jmap_request = JMapRequest.from_json(request_json)
        except JMapRequestError as exc:
            return exc.to_json()

        executor = Executor(modules=self.modules)

        try:
            jmap_response = executor.execute(jmap_request, context=context)
        except JMapError as exc:
            return exc.to_json()

        return jmap_response.to_json()