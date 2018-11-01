from jmap.protocol.jsonpointer import resolve_pointer


def test_wildcard():
    result = resolve_pointer({
        'foo': [
            {'id': 1},
            {'id': 12},
        ]
    }, '/foo/*/id')

    assert result == [1, 12]