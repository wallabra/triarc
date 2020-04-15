"""Bots are the central concept of Triarc: entities that
manage high-level responses, while leaving low-level handling
details to the backend(s).
"""

from typing import Optional, Set

import warnings
import traceback
import functools

import trio
import triarc

from triarc.backend import Backend
from triarc.mutator import Mutator
from triarc.errors import TriarcBotBackendRefusedError



class Message:
    def __init__(self, backend, line, author_name, author_addr, channel):
        self.backend = backend
        self.line = line
        self.author_name = author_name
        self.author_addr = author_addr
        self.channel = channel

    async def reply(self, reply_line):
        pass

    def __repr__(self):
        return '{}({} in {}: {})'.format(type(self).__name__, self.author_name, self.channel, repr(self.line))


class Bot:
    """
    A bot superclass. It is supposed to be subclassed in order to be used, you know.
    """

    def __init__(self, name: str, backends: Set[Backend] = ()):
        """
        Arguments:
            name {str} -- A descriptive name for your Triarc bot.

        Keyword Arguments:
            backends {Set[triarc.backend.Backend]} -- A list of backends for the bot to harness.
        """

        self.name = name
        self.mutators = set() # type: Set[Mutator]
        self.backends = set() # type: Set[Backend]

        backends = set(backends)

        for backend in backends:
            self.register_backend(backend)

    def register_mutator(self, mutator: Mutator):
        """
        Registers an individual mutator.

        Arguments:
            mutator {triarc.mutator.Mutator} -- A single mutator to register to this bot.
        """

        self.mutators.add(mutator)

        for backend in self.backends:
            backend._register_mutator(mutator)

    def register_backend(self, backend: Backend, required: bool = False):
        """
        Registers an individual backend.

        Arguments:
            backend {triard.backend.Backend} -- A single backend to register to this bot.

        Keyword Arguments:
            required {bool} --  Whether the Backend refusing to be registered should raise
                                an exception; see triarc.backend.Backend.pre_bot_register
                                for more info on that.
        """

        if not backend.pre_bot_register(self):
            self.backends.add(backend)

            backend.listen_all()(functools.partial(self._specific_on_relay, backend))
            backend.listen_all()(functools.partial(self.on_any, backend))

            for mutator in self.mutators:
                backend._register_mutator(mutator)

            backend.post_bot_register(self)

        elif required:
            raise TriarcBotBackendRefusedError("Backend", backend, "refused to be registered by bot", self)

    async def respond(self, which: Backend, source: Message, message: str) -> bool:
        """Replies to commands. Deprecated; use Message.reply instead!

        Arguments:
            which {Backend} -- The backend in the which to send the message.
            source {Message} -- The source to reply to.
            message {str} -- The message to send.

        Returns: whether the message has been sent. (type: {bool})
        """

        await source.reply(message)

        return True

    def any_listener(self, func):
        """
        Adds a listener that is called on any backend event.
        """

        for backend in self.backends:
            backend.listen_all()(functools.partial(func, self, backend))

        return func

    async def on_any(self, which: Backend, kind: str, data: any):
        """This method is called on every backend event.

        Arguments:
            which {Backend} -- The backend responsible for this event.
            kind {str} -- The kind of event emitted by the underlying backend.
            data {any} -- The event's data.
        """
        pass

    async def _specific_on_relay(self, which: Backend, kind, data, _sent = ()):
        """
            >>> import trio
            ...
            >>> dummy_backend = Backend()
            ...
            >>> class MyBot(Bot):
            ...     async def on_hello(_, self, name):
            ...         print('Hello, {}!'.format(name))
            ...
            >>> bot = MyBot([dummy_backend])
            ...
            >>> trio.run(dummy_backend.receive_message, 'hello', 'everyone')
            ...
            Hello, everyone!
        """

        _sent = set(_sent) | {kind}

        func_name = 'on_{}'.format(kind.lower())

        for mutator in self.mutators:
            await mutator.on_any(which, kind, data)

            if hasattr(mutator, func_name):
                await getattr(mutator, func_name)(which, data)

        if hasattr(self, func_name):
            await getattr(self, func_name)(which, data)

    def init(self):
        """Called before the backend is started."""

    def pre_deinit(self):
        """Called right before stopping."""

    def deinit(self):
        """Called right after the bot has stopped, and
        after all of its backends have been gracefully
        stopped."""

    async def start(self):
        """Starts this Bot by starting its backend."""

        self.init()

        async with trio.open_nursery() as nursery:
            for backend in self.backends:
                nursery.start_soon(backend.start)

    async def stop(self):
        """Stops this Bot by stopping its backend."""

        self.pre_deinit()

        async with trio.open_nursery() as nursery:
            for backend in self.backends:
                nursery.start_soon(backend.stop)

        self.deinit()

    def __repr__(self):
        return "{}('{}': {} backends)".format(type(self).__name__, self.name, len(self.backends))


class CommandBot(Bot):
    """
    A Bot subclass that responds to commands.

    CommandBot subclasses can use the init method to
    add commands, or load plugins that do so.
    """

    def __init__(self, backends: Set[Backend], prefix: str = "'"):
        """
        Arguments:
            backend {Set[triarc.backend.Backend]} -- This bot's backend(s).

        Keyword Arguments:
            prefix {str} -- The bot command to use (default: {"'"})
        """

        super().__init__(backends)

        self.prefix = prefix
        self.commands = {}
        self.help = {}

    async def on_message(self, which: Backend, message: Message):
        try:
            target = message.target
            line = message.line

            line = line.rstrip()

            if line.startswith(self.prefix):
                line = line[len(self.prefix):]

                cmd = line.split(' ')[0]
                args = line.split(' ')[1:]

                if cmd in self.commands:
                    try:
                        await self.commands[cmd](which, message, *args)

                    # (We are meant to catch exceptions broadly, in order to
                    # report them to bot authors.)
                    # pylint: disable=broad-except
                    except Exception as err:
                        traceback.print_exc()
                        await self.respond(which, target, '{}: {}'.format(type(err).__name__, str(err)))

        except Exception:
            traceback.print_exc()
            raise

    async def read(self, which: Backend, target: any, message: str, data: "triarc.irc.IRCResponse"):
        """
        Deprecated method. Do not use.

        Arguments:
            target {any} -- Any object the backend treats as a target.

            message {str} -- The line to read.

        Keyword Arguments:
            data {IRCResponse} --   An IRC response object.
        """

        await self.on_message(which, Message(which, message, data.origin, data.origin, target))


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
            _target = [None]
            _which = [None]

            def define(definition): # definition is the function
                async def _inner(which: Backend, targ: str, *args, **kwargs):
                    _which[0] = which
                    _target[0] = targ

                    return await definition(*args, **kwargs)

                self.commands[name] = _inner

            if help_string:
                self.help['commands.' + name] = help_string

            async def _reply(msg: str):
                if not _target[0]:
                    warnings.warn('Target not set in add_command! Please report this bug.')

                elif not _which[0]:
                    warnings.warn(
                        'Source backend not set in add_command! Please report this bug.'
                    )

                else:
                    await self.respond(_which[0], _target[0], msg)
                    return True

                return False

            return func(define, _reply)

        return _decorator
