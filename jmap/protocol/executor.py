"""
Knows how to execute a JMAP request.
"""

from collections import defaultdict
from typing import List, Dict, Any

from marshmallow import ValidationError

from jmap.protocol.core import JmapModuleInterface
from jmap.protocol.errors import JMapError, JMapMethodError, JMapUnknownMethod, JMapInvalidResultReference, \
    JMapNotRequest
from jmap.protocol.jsonpointer import resolve_pointer, JsonPointerException
from jmap.protocol.models import JMapRequest, JMapResponse, ResultReference


class MethodNotFound(JMapError):
    pass


def resolve_reference(ref: ResultReference, db: Dict[str, Dict[str, Any]]):
    """
    Resolve a JMAP reference to a previous method call result.
    """
    if not ref.result_of in db:
        raise JMapInvalidResultReference('Not found a previous method call with id {}'.format(ref.result_of))
    responses = db[ref.result_of]

    if not ref.name in responses:
        raise JMapInvalidResultReference('Previous method call with id "{}" has no response named "{}", possible names are: {}'.format(
            ref.result_of, ref.name, ", ".join(responses.keys())))

    response = responses[ref.name]

    try:
        return resolve_pointer(response.to_client(), ref.path)
    except JsonPointerException as exc:
        raise JMapInvalidResultReference('{}'.format(exc))


class Executor:
    """You can pass this a `JMapRequest`.

    It will parse the request, validate it, and return a serialized response.

    It will defer to the list of `modules`. The interface that modules implement is
    very thin; the executor largely just passes each method call included in the JMAP
    request to each module's `execute()`. The validation logic must be handled by the
    module. The `JMapModule` base class implements this logic in a re-usable way.

    TODO: We might convert this into a stateless function, to make it clear there is
    no need to instantiate this only once.
    """

    def __init__(self, modules: List[JmapModuleInterface]):
        # Map all method names to modules
        self.available_methods = {method: m for m in modules for method in m.get_methods()}

    def execute(self, request: JMapRequest):
        method_responses = []

        # Keep previous responses to allow references
        responses_by_client_id = defaultdict(lambda: {})

        for method_call in request.method_calls:
            try:
                result = self.execute_method(method_call, responses_by_client_id=responses_by_client_id)
            except JMapMethodError as exc:
                response_name = 'error'
                response_data = exc.to_json()
            else:
                response_name = method_call.name
                response_data = result

            # Index it
            responses_by_client_id[method_call.client_id][response_name] = response_data

            method_responses.append(
                [
                    response_name,
                    response_data,
                    method_call.client_id
                ]
            )

        return JMapResponse(method_responses=method_responses)

    def execute_method(self, method_call, *, responses_by_client_id):
        # Find the right module
        if not method_call.name in self.available_methods:
            raise MethodNotFound(method_call.name)
        module = self.available_methods[method_call.name]

        # Resolve any references to previous responses
        args = method_call.args
        if isinstance(args, dict):
            for arg_name in list(args.keys()):
                if arg_name.startswith('#'):
                    try:
                        # TODO: Do this earlier during request parsing
                        ref = ResultReference.from_client(args[arg_name])
                    except ValidationError as exc:
                        raise JMapNotRequest(str(exc))
                    new_value = resolve_reference(ref, responses_by_client_id)
                    args[arg_name[1:]] = new_value
                    del args[arg_name]

        # Execute the call
        try:
            return module.execute(method_call.name, args)
        except NotImplementedError:
            raise JMapUnknownMethod("This method is not implemented.")