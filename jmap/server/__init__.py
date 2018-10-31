from flask import Flask, request, jsonify, url_for
from jmap.protocol import JMapRequest
from jmap.protocol.core import CoreLibrary
from jmap.protocol.executor import Executor


app = Flask(__name__)


@app.route("/.well-known/jmap", methods=['GET'])
def jmap_auth():
    """
    See "2. The JMAP Session resource"
    """

    return jsonify({
        "username": 'user@domain.com',
        "primaryAccounts": {},
        "accounts": {
            "13824": {
                "name": "john@example.com",
                "isPersonal": True,
                "isReadOnly": False,
                "hasDataFor": [
                    "urn:ietf:params:jmap:mail",
                    "urn:ietf:params:jmap:contacts"
                ]
            },
        },
        "capabilities": {},
        "apiUrl": url_for('jmap_api'),
        "uploadUrl": '/upload',
        "downloadUrl": '/download',
        "eventSourceUrl": 'signId1',
        "state": None,

        # jmap-client requires this, but it is not part of the spec
        'accessToken': "test",
        "signingId": "test",
        "signingKey": "test",
    })


@app.route("/", methods=['POST'])
def jmap_api():
    jmap_request = JMapRequest.from_json(request.json)
    executor = Executor(libraries=[CoreLibrary()])
    jmap_response = executor.execute(jmap_request)

    return jsonify(jmap_response.to_json())
