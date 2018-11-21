import json
from datetime import datetime

import pytest
from marshmallow import ValidationError

from jmap.protocol.models import Email, HeaderFieldQuery, EmailBodyPart, \
    EmailGetArgs, HeaderFieldForm, QueriedHeaderField



def test_header_values_in_properties():
    """
    EmailGetArgs has a field "properties" which is a complicated case. It lists
    the properties of `Email` the client wants to query. However, it also:

    - Needs to convert from camelCase to snake_case.
    - Needs to allow for arbitrary header:* queries.
    """

    x = EmailGetArgs.from_server(dict(
        accountId="1",
        properties=[
            'header:Foo:asMessageIds',
            'messageId'
        ]
    ))
    assert x.properties == [
        HeaderFieldQuery(name='Foo', form=HeaderFieldForm.message_ids, all=False),
        'message_id'
    ]

    assert x.to_server()['properties'] == ['header:Foo:asMessageIds', 'messageId']


    # Test error cases:

    with pytest.raises(ValidationError):
        EmailGetArgs.from_server(dict(
            accountId="1",
            properties=[
                'not right',
            ]
        ))

    with pytest.raises(ValidationError):
        EmailGetArgs.from_server(dict(
            accountId="1",
            properties=[
                'header:Foo:asMessageIDS',
            ]
        ))

    with pytest.raises(ValidationError):
        EmailGetArgs.from_server(dict(
            accountId="1",
            properties=[
                'header:Foo:asdf',
            ]
        ))

    with pytest.raises(ValidationError):
        EmailGetArgs.from_server(dict(
            accountId="1",
            properties=[
                'header',
            ]
        ))


def test_from_property():
    EmailGetArgs.from_client({
        'accountId': '1',
        'properties': [ 'from']
    })


def test_email_header():
    # This is testing we can use the header:** property when parsing an email
    em = Email(
        id='1',
        blob_id='1',
        thread_id='1',
        mailbox_ids={'1': True},
        size=1,
        received_at=datetime.utcnow(),
        headers=[],
        has_attachment=False,
        attachments=[],
        body_structure=EmailBodyPart(headers=[], type=""),
        preview="",
        text_body=[],
        html_body=[],
        body_values={},

        header_fields=[
            QueriedHeaderField(
                name="From",
                value="1"
            )
        ]
    )

    print(json.dumps(em.to_server(), indent=2))
    assert em.to_server()['header:From:asRaw'] == "1"

    x = Email.from_server({
      "bodyStructure": {
        "type": "",
        "headers": []
      },
      "headers": [],
      "attachments": [],
      "hasAttachment": False,
      "preview": "",
      "mailboxIds": {
        "1": True
      },
      "textBody": [],
      "id": "1",
      "htmlBody": [],
      "bodyValues": {},
      "threadId": "1",
      "keywords": {},
      "blobId": "1",
      "receivedAt": "2014-12-22T03:12:58.019077+00:00",
      "size": 1,
      "header:From:asRaw": "1"
    })