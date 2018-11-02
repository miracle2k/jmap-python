from jmap.protocol.jsonpointer import resolve_pointer


def test_wildcard_to_int():
    result = resolve_pointer({
        'foo': [
            {'id': 1},
            {'id': 12},
        ]
    }, '/foo/*/id')

    assert result == [1, 12]


def test_wildcard_to_array():
    result = resolve_pointer({
        'foo': [
            {'id': [1, 2]},
            {'id': [12]},
        ]
    }, '/foo/*/id')

    assert result == [1, 2, 12]