"""Bots are the central concept of Triarc: entities that
manage high-level responses, while leaving low-level handling
details to the backend(s).
"""

import warnings
import traceback
import functools
from typing import Optional, Set

import trio

from triarc.backend import Backend
from triarc.mutator import Mutator




class Bot:
    """
    A bot superclass. It is supposed to be subclassed in order to be used, you know.
    """

    def __init__(self, backends: Set[Backend]):
        """
        Arguments:
            backends {Set[Backend]} -- A list of backends for the bot to harness.
        """

        self.backends = backends
        self.mutators = set() # type: Set[Mutator]
        
        for backend in self.backends:
            backend.listen_all()(functools.partial(self._specific_on_relay, backend))
            backend.listen_all()(functools.partial(self.on_any, backend))

    async def respond(self, which: Backend, target: str, message: str) -> bool:
        """Replies to commands.

        Arguments:
            which {Backend} -- The backend in the which to send the message.
            target {str} -- The target (e.g. channel or user on IRC) to send reply messages to.
            message {str} -- The message to send.

        Returns: whether the message has been sent. (type: {bool})
        """

        for mutator in self.mutators:
            message = mutator.modify_message(which, target, message)

            if not message:
                return False

        await which.message(target, message)

        return True

    def any_listener(self, func):
        """
        Adds a listener that is called on any backend event.
        """
        
        for backend in self.backends:
            backend.listen_all()(functools.partial(func, self, backend))
        
        return func

    def register_mutator(self, mutator: Mutator):
        """
        Registers a Mutator, so it can be used with this bot.
        """

        self.mutators.add(mutator)

        for backend in self.backends:
            backend.listen_all()(functools.partial(mutator.on_any, backend))

        mutator.registered(self)

    async def on_any(self, which: Backend, kind: str, data: any):
        """This method is called on every backend event.

        Arguments:
            which {Backend} -- The backend responsible for this event.
            kind {str} -- The kind of event emitted by the underlying backend.
            data {any} -- The event's data.
        """

    async def _specific_on_relay(self, which: Backend, kind, data):
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

        func_name = 'on_{}'.format(kind.lower())

        if hasattr(self, func_name):
            await getattr(self, func_name)(which, data)

        for mutator in self.mutators:
            if hasattr(mutator, func_name):
                await getattr(mutator, func_name)(self, which, data)

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


class CommandBot(Bot):
    """
    A Bot subclass that responds to commands.

    CommandBot subclasses can use the init method to
    add commands, or load plugins that do so.
    """

    def __init__(self, backends: Set[Backend], prefix: str = "'"):
        """
        Arguments:
            backend {Set[Backend]} -- This bot's backend(s).

        Keyword Arguments:
            prefix {str} -- The bot command to use (default: {"'"})
        """

        super().__init__(backends)

        self.prefix = prefix
        self.commands = {}
        self.help = {}

    async def read(self, which: Backend, target: str, message: str, data: any = None):
        """CommandBot subclasses must call this function
        whenever messages are received from others,
        in order to find and process potential commands.

        Arguments:
            target {str} -- The target (e.g. channel or user on IRC) to send command
                            answers to, by default.

            message {str} -- The line to read.

        Keyword Arguments:
            data {any} --   Any object that holds information about this event,
                            such as an IRC server response (default: None)
        """

        message = message.rstrip()

        if message.startswith(self.prefix):
            message = message[len(self.prefix):]

            cmd = message.split(' ')[0]
            args = message.split(' ')[1:]

            if cmd in self.commands:
                try:
                    await self.commands[cmd](which, target, data, *args)

                # (We are meant to catch exceptions broadly, in order to
                # report them to bot authors.)
                # pylint: disable=broad-except
                except Exception as err:
                    traceback.print_exc()
                    await self.respond(which, target, '{}: {}'.format(type(err).__name__, str(err)))

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
