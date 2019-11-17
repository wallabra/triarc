import warnings

from triarc.backend import Backend
from typing import Optional



class Bot(object):
    def __init__(self, backend: Backend):
        self.backend = backend

        self.backend.listen_all()(self._specific_on_relay)
        self.backend.listen_all()(self.on)

    async def on(self, kind, data):
        pass

    async def _specific_on_relay(self, kind, data):
        """
            >>> import trio
            ...
            >>> dummy_backend = Backend()
            ...
            >>> class MyBot(Bot):
            ...     async def on_hello(self, name):
            ...         print('Hello, {}!'.format(name))
            ...
            >>> bot = MyBot(dummy_backend)
            ...
            >>> trio.run(dummy_backend.receive_message, 'hello', 'everyone')
            ...
            Hello, everyone!
        """

        f = getattr(self, 'on_{}'.format(kind.lower()), None)

        if f:
            await f(data)

    def init(self):
        """Called before the backend is started."""
        pass

    def pre_deinit(self):
        """Called right before stopping."""
        pass

    def deinit(self):
        """Called right after the bot has stopped."""
        pass

    async def start(self):
        """Starts this Bot by starting its backend."""

        self.init()
        await self.backend.start()

    async def stop(self):
        """Stops this Bot by stopping its backend."""

        self.pre_deinit()
        await self.backend.stop()
        self.deinit()


class CommandBot(Bot):
    def __init__(self, backend: Backend, prefix: str = "'"):
        """A Bot subclass that responds to commands.

        CommandBot subclasses can use the init method to
        add commands, or load plugins that do so.
        
        Arguments:
            backend {Backend} -- This bot's backend.
        
        Keyword Arguments:
            prefix {str} -- The bot command to use (default: {"'"})
        """

        super().__init__(backend)

        self.prefix = prefix
        self.commands = {}
        self.help = {}

    async def respond(self, to: str, message: str):
        """CommandBot subclasses must implement this
        method, which replies to commands.
        
        Arguments:
            to {str} -- The target (e.g. channel or user on IRC) to send reply messages to.
            message {str} -- The message to send.
        """

        pass

    async def read(self, target: str, message: str):
        """CommandBot subclasses must call this function
        whenever messages are received from others,
        in order to find and process potential commands.
        
        Arguments:
            target {str} -- The target (e.g. channel or user on IRC) to send command answers to, by default.
            message {str} -- The line to read.
        """

        message = message.rstrip()

        if message.startswith(self.prefix):
            message = message[len(self.prefix):]

            cmd = message.split(' ')[0]
            args = message.split(' ')[1:]

            if cmd in self.commands:
                try:
                    await self.commands[cmd](target, *args)

                except Exception as err:
                    await self.respond(target, '{}: {}'.format(type(err).__name__, str(err)))

    def add_command(self, name: str, help_string: Optional[str] = None):
        """Adds a commannd to this bot, by supplying a define function and an asynchronous
        reply method. Use a closure (decorated with the 'define' argument) to actually define
        the command.
        
        Arguments:
            name {str} -- The name of the command.
        
        Keyword Arguments:
            help_string {Optional[str]} -- [description] (default: {None})
        """

        def _decorator(func):
            target = [None]

            def define(definition): # definition is the function
                async def _inner(targ, *args, **kwargs):
                    target[0] = targ
                    return await definition(*args, **kwargs)

                self.commands[name] = _inner

            if help_string:
                self.help['commands.' + name] = help_string

            async def _reply(msg):
                if target[0]:
                    await self.respond(target[0], msg)

                else:
                    warnings.warn('Target not set in add_command! Please report this bug.')
                
            return func(define, _reply)

        return _decorator
