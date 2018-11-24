class JMapError(Exception):
    pass


class JMapMethodError(JMapError):
    """
    A method level error  (3.5.2 Method-level errors, https://jmap.io/spec-core.html#errors).
    """

    typename = None

    def __init__(self, description = None):
        super().__init__(description)
        self.description = description

    def to_json(self):
        result = {
            'type': self.typename
        }
        if self.description:
            result['description'] = self.description
        return result


class JMapUnknownMethod(JMapMethodError):
    typename = 'unknownMethod'


class JMapInvalidArguments(JMapMethodError):
    typename = 'invalidArguments'


class JMapUnsupportedFilter(JMapMethodError):
    typename = 'unsupportedFilter'


class JMapInvalidResultReference(JMapMethodError):
    typename = 'invalidResultReference'


class JmapCannotCalculateChanges(JMapMethodError):
    typename ='cannotCalculateChanges'


class JMapRequestError(JMapError):
    """
    A request level error  (3.5.1 Request-level errors, https://jmap.io/spec-core.html#errors).
    """

    typename = None
    statuscode = None

    def __init__(self, detail = None):
        super().__init__(detail)
        self.detail = detail

    def to_json(self):
        return {
          "type": f"urn:ietf:params:jmap:error:{self.typename}",
          "status": self.statuscode,
          "detail": self.detail
        }


class JMapNotRequest(JMapRequestError):
    """
    urn:ietf:params:jmap:error:notRequest
    The request parsed as JSON but did not match the structure of the Request object.
    """
    typename = 'notRequest'
    statuscode = 400
    detail = 'This was not a valid request structure'


class SetError(Exception):
    pass


class SetErrorNotFound(SetError):
    pass