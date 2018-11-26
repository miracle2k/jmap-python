import inspect
from typing import Any, Dict

from marshmallow import ValidationError

from jmap.models.errors import JMapError, JMapInvalidArguments


class JmapModuleInterface:

    """
    This describes the interface that the executor expects.
    """

    def get_methods(self):
        raise NotImplementedError()

    def execute(self, method_name, args, *, context=None):
        """
        Usually, the method would just return a dict. But the spec in 3.3.1 seems
        to indicate that a method can return multiple responses. In such a case,
        we would require this method to return a list of 2-tuples, each response needing
        a custom name. Or, we could use a custom object.
        """
        raise NotImplementedError()


class JmapBaseModule(JmapModuleInterface):

    """
    This defines a certain way of defining module subclasses. Helps with validating
    arguments, permission checks.
    """

    def __init__(self, *, auth_backend: Any = None):
        self.methods = {}
        self.auth_backend = auth_backend

    def get_state_for(self, type: str):
        """
        Return the state for the given data type.
        """
        raise NotImplementedError()

    def get_methods(self):
        return set(self.methods.keys())

    def execute(self, method_name, input: Dict, *, context=None):
        method = self.methods[method_name]

        # Figure out the arguments to the method
        spec = inspect.getfullargspec(method)
        if len(spec.args) != 3:
            raise TypeError(f'The method {method} is expected to have exactly two '
                            f'arguments. The expected signature is (context, args).')

        arg_name_for_methog_args = spec.args[2]
        if not arg_name_for_methog_args in spec.annotations:
            raise TypeError(f'The second argument to {method} is expected to represent '
                            f'the JMAP method args. It must be annotated with a '
                            f'marshallable type.')
        type = spec.annotations[arg_name_for_methog_args]

        # We special case "Any". If this is the type, we just pass the
        # input data through.
        if type is Any:
            arg_object = input
        else:
            if isinstance(input, dict):
                try:
                    arg_object = type.from_client(input)
                except ValidationError as exc:
                    raise JMapInvalidArguments(str(exc))
            else:
                arg_object = input

        return self.methods[method_name](context, arg_object)


class CoreModule(JmapBaseModule):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.methods = {
            'Core/echo': self.handle_echo,
            'Blog/copy': self.handle_blob_copy,
            'getAccounts': self.handle_get_accounts,
        }

    def handle_echo(self, context, args: Any):
        return args

    def handle_get_accounts(self, context, args):
        # No longer exists:
        # https://groups.google.com/forum/#!topic/jmap-discuss/9XKdZrp2mBE
        # https://github.com/linagora/jmap-client/commit/966c4e787f69c5def82273b8f677d28f264f9e0f
        raise JMapError('Old method')

    def handle_blob_copy(self, args):
        pass