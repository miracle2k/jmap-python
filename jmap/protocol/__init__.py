from typing import List, Any, Dict
from dataclasses import dataclass


@dataclass
class MethodCall:
    name: str
    args: Dict[str, Any]
    client_id: str


@dataclass
class JMapRequest:
    using: List[str]
    method_calls: List[MethodCall]
    
    @staticmethod
    def from_json(data):
        # This is not mentioned in the spec directly, but the echo example (4.1)
        # suggests this kind of shortened message, and clients in the wild
        # (linagora/jmap-client) send this kind of response, so support it.
        if isinstance(data, list):
            methods = parse_methods(data)
            return JMapRequest(
                using=[],
                method_calls=methods
            )

        if isinstance(data, dict):
            methods = parse_methods(data.get('methodCalls'))
            return JMapRequest(
                using=data.get('using', []),
                method_calls=methods
            )

        raise ValueError("Invalid request: {}".format(data))


def parse_methods(data):
    methods = []
    for call in data:
        method_name, args, client_id = call
        methods.append(MethodCall(name=method_name, args=args, client_id=client_id))
    return methods



@dataclass
class JMapResponse:
    method_responses: List[Any]

    def to_json(self):
        return {
            'methodResponses': self.method_responses
        }