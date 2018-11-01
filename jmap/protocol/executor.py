"""
Knows how to execute a JMAP request.
"""

from typing import List
from jmap.protocol.core import JmapModuleInterface, JMapError
from jmap.protocol.models import JMapRequest, JMapResponse


class MethodNotFound(JMapError):
    pass


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

        for method_call in request.method_calls:
            if not method_call.name in self.available_methods:
                raise MethodNotFound(method_call.name)

            module = self.available_methods[method_call.name]

            # Execute the call
            result = module.execute(method_call.name, method_call.args)
            method_responses.append(
                [
                    method_call.name,
                    result,
                    method_call.client_id
                ]
            )

        return JMapResponse(method_responses=method_responses)