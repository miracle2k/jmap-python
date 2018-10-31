class CoreLibrary:

    NAME = "Core"

    def execute(self, method_name, args):
        """
        Usually, the method would just return a dict. But the spec in 3.3.1 seems
        to indicate that a method can return multiple responses. In such a case,
        we would require this method to return a list of 2-tuples, each response needing
        a custom name. Or, we could use a custom object.        
        """
        if method_name == 'echo':
            return self.handle_echo(args)

        if method_name == 'getAccounts':
            return self.handle_get_accounts(args)

        raise MethodNotFound()

    def handle_echo(self, args):
        return args

    def handle_get_accounts(self, args):
        # No longer exists:
        # https://groups.google.com/forum/#!topic/jmap-discuss/9XKdZrp2mBE
        # https://github.com/linagora/jmap-client/commit/966c4e787f69c5def82273b8f677d28f264f9e0f
        raise CommandError('Old method')