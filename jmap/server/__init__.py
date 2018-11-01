"""
For testing, a JMAP server.

TODO: Make this SansIO.
"""
import attr
from flask import Flask, request, jsonify, url_for
from flask.json import JSONEncoder
from flask_cors import CORS, cross_origin

from jmap.protocol.models import JMapRequest, Account, MAIL_URN
from jmap.protocol.core import CoreModule
from jmap.protocol.executor import Executor
from jmap.server.accounts import StaticBackend
from jmap.server.fixture import FixtureEmailModule
from jmap.server.modules.maildir import MboxModule


class CustomJSONEncoder(JSONEncoder):

    def default(self, obj):
        if attr.has(type(obj)):
            if getattr(obj, 'marshal'):
                return obj.marshal()
            return attr.asdict(obj)
        return JSONEncoder.default(self, obj)


app = Flask(__name__)
app.json_encoder = CustomJSONEncoder
CORS(app)


auth_backend = StaticBackend({
    'foo': Account(
        name="test",
        is_personal=True,
        is_read_only=False,
        has_data_for=[MAIL_URN]
    )
})
email_module = MboxModule(
    './samples/sample.mbox',
    auth_backend=auth_backend
)


def validate_request_auth():
    # However that might work,
    pass


@app.route("/.well-known/jmap", methods=['GET'])
@cross_origin()
def jmap_auth():
    """
    See "2. The JMAP Session resource"
    """

    accounts = auth_backend.get_accounts_for(None)

    return jsonify({
        "username": 'user@domain.com',
        "primaryAccounts": {},
        "accounts": {
            account_id: account.marshal()
            for account_id, account in accounts.items()
        },

        "capabilities": {},
        "apiUrl": request.host_url + url_for('jmap_api')[:-1],
        "uploadUrl": '/upload',
        "downloadUrl": '/download',
        "eventSourceUrl": '/events',
        "state": None,

        # jmap-client requires this, but it is not part of the spec
        'accessToken': "test",
        "signingId": "test",
        "signingKey": "test",
    })


@app.route("/", methods=['POST'])
@cross_origin(supports_credentials=True)
def jmap_api():
    jmap_request = JMapRequest.from_json(request.json)
    executor = Executor(modules=[CoreModule(), email_module])
    jmap_response = executor.execute(jmap_request)

    return jsonify(jmap_response.to_json())


@app.route("/events", methods=['GET'])
@cross_origin()
def jmap_events():
    """
    TODO: Serve events.

    This would use a different kind of backend structure. This may
    mean polling in some cases.
    """