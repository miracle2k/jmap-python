"""
Knows how to execute a JMAP request.
"""

from typing import Any, Dict, List
from jmap.protocol import JMapRequest, JMapResponse


class Executor:

    def __init__(self, libraries: List[Any]):
        self.libraries = {l.NAME: l for l in libraries}

    def execute(self, request: JMapRequest):
        method_responses = []

        for method_call in request.method_calls:
            library = None

            try:
                library_name, method_name = method_call.name.split('/', 1)
            except ValueError:
                library = self.libraries['Core']
                method_name = method_call.name
            else:
                # Find the library
                library = self.libraries[library_name]

            # Execute the call
            result = library.execute(method_name, method_call.args)
            method_responses.append(
                [
                    method_call.name,
                    result,
                    0
                ]
            )

        return JMapResponse(method_responses=method_responses)