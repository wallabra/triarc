"""
The Backend class.

The base class of all Triarc backends is here defined.
"""

import attr
import logging
import queue
import typing
import uuid
from collections.abc import Iterable

import trio

from .mutator import Mutator
from .comms.base import CompositeContentType
from .comms.impl import ChannelProxy, UserProxy

if typing.TYPE_CHECKING:
    from typing import Optional

    from .comms.tosend import MessageToSend

BackendType = typing.TypeVar("BackendType", "Backend")


@attr.s(auto_attribs=True)
class Backend(typing.Protocol):
    """
    Dummy backend implementation superclass.

    Actual Triarc backends are supposed to subclass the Backend class, which
    nonetheless provides several utilities, including those which are expected
    (and thus required) by the Triarc bot that will eventually use it.
    """

    identifier: str = attr.Factory(
        lambda identifier: identifier if identifier is not None else str(uuid.uuid4())
    )
    mutators: dict[str, Mutator] = attr.Factory(dict)
    listeners: dict[str, set[typing.Callable[[str, any], None]]] = attr.Factory(dict)
    globallisteners: dict[str, set[typing.Callable[[str, any], None]]] = attr.Factory(
        dict
    )

    stop_scopes: set = attr.Factory(set)
    stop_scope_watcher: typing.Optional[trio.NurseryManager] = None

    def get_composite_types(self) -> Iterable[CompositeContentType]:
        """Get a list of all CompositeContent implementation types supported."""
        return []

    def _register_mutator(self, mutator: Mutator):
        self.mutators.add(mutator)

    def _mutate_reply(self, target: str, reply: str) -> str:
        for mut in self.mutators:
            reply = mut.modify_message(self, target, reply)

        return reply

    def listen(self, name: str = "_"):
        """Adds a listener for specific messages received in this backend.
        Use as a decorator generating method.

        Keyword Arguments:
            name {str} -- The name of the event to listen for (default: {'_'})

        Returns:
            function -- The decorator method.
        """

        def _decorator(func):
            self.listeners.setdefault(name, set()).add(func)
            return func

        return _decorator

    def listen_all(self):
        """Adds a listener for all messages received in this backend.
        Use as a decorator generating method.

        Returns:
            function -- The decorator method.
        """

        def _decorator(func):
            self.globallisteners.add(func)
            return func

        return _decorator

    async def receive_message(self, kind: str, data: any):
        """Call this function whenever a message is received in this backend.
        Used either by subclasses or to 'simulate' messages.

            >>> import trio
            >>> dummy_backend = Backend()
            >>> adjective = 'great'
            ...
            >>> @dummy_backend.listen('No')
            ... async def no(whom, data):
            ...     print("Whom?")
            ...
            >>> @dummy_backend.listen('Yes')
            ... async def yes(whom, data):
            ...     print("You should also listen to {} – {}. It's {}. :)"
            ...         .format(whom, data, adjective)
            ...     )
            ...
            >>> async def test_me():
            ...     await dummy_backend.receive_message('Yes', 'Talk')
            ...
            ...     global adjective
            ...     adjective = 'superb'
            ...
            ...     await dummy_backend.receive_message('Yes', 'Relayer')
            ...     await dummy_backend.receive_message('No',
            ...         '(I don\\'t know this band ;-;)'
            ...     )
            ...
            >>> trio.run(test_me)
            You should also listen to Yes – Talk. It's great. :)
            You should also listen to Yes – Relayer. It's superb. :)
            Whom?

        Arguments:
            kind {str} -- The kind of message (aka name argument in listen).
            data {any} -- The message's data.
        """

        lists = self.listeners.get(kind, set()) | self.globallisteners

        for listener in lists:
            await listener(kind, data)

        # async with trio.open_nursery() as nursery:
        #    for listener in lists:
        #        nursery.start_soon(listener, kind, data)

    async def start(self):
        """Starts the backend."""
        ...

    async def stop(self):
        """Stops the backend."""
        ...

    async def message(self, target: str, message: str):
        """Standard backend method, which must be implemented by
        every backend. Sends a message to a target.

        Arguments:
            target {str} -- The target of the message (user, channel, etc).
            message {str} -- The message to be sent.
        """
        ...

    def message_sync(self, target: str, message: str):
        """Synchronous backend method, which must be implemented by
        every backend if possible (and raise a RuntimeError if it
        is not possible). Sends a message to a target, without blocking.

        Arguments:
            target {str} -- The target of the message (user, channel, etc).
            message {str} -- The message to be sent.
        """
        ...

    def post_bot_register(self, bot):
        """
        Called after a Bot registers this Backend.

        Used so that the backend can perform further
        useful operations on the bot.

        Arguments:
            bot {triarc.bot.Bot}: The Bot that registers this Backend.
        """
        ...

    def pre_bot_register(self, bot):
        """
        Caled when a Bot attempts to register this Backend; more
        precisely, before it actually does so.

        This backend may use this function to cancel the registering,
        simply by returning a value that has a boolean value of True
        (bool(x) is True).

        Arguments:
            bot {triarc.bot.Bot}: The Bot that wants to register this Backend.
        """
        return False

    async def _watch_stop_scopes(self, on_loaded):
        async with trio.open_nursery() as nursery:
            self.stop_scope_watcher = nursery

            async def _run_until_stopped():
                while self.running():
                    await trio.sleep(0.05)

            nursery.start_soon(_run_until_stopped)
            nursery.start_soon(on_loaded)

    def construct_message_lines(self, *lines: typing.Iterable[str]) -> "MessageToSend":
        """
        Constructs a new MessageToSend object from one or more
        lines of plaintext.
        """
        raise NotImplementedError("This method is implemented in subclasses!")

    def new_stop_scope(self):
        """
        Makes a new Trio cancel scope, which is automatically
        cancelled when the backend is stopped. The backend must
        be running.

        Raises:
            RuntimeError: Tried to make a stop scope whilst not running.

        Returns:
            trio.CancelScope -- The stop scope.
        """
        scope = trio.CancelScope()
        self.stop_scopes.add(scope)

        if self.stop_scope_watcher:

            async def watch_scope(scope):
                while not scope.cancel_called:
                    await trio.sleep(0.2)

                self.stop_scopes.remove(scope)
                del scope

            self.stop_scope_watcher.start_soon(watch_scope, scope)

        else:
            raise RuntimeError(
                "Tried to obtain a stop scope while the backend isn't running!"
            )

        return scope

    def get_channel(self, addr: str) -> typing.Optional[ChannelProxy]:
        """Returns a ChannelProxy from a channel address or identifier."""
        ...

    def get_user(self, addr: str) -> typing.Optional[UserProxy]:
        """Get an UserProxy from an user address or identifier."""
        ...


@attr.s(auto_attribs=True)
class ThrottledBackend(Backend, typing.Protocol):
    """
    A backend that supports throttling.
    """

    cooldown_hertz: float = 1.2
    max_heat: int = 5
    throttle: bool = True
    logger: logging.Logger = attr.Factory(lambda: None)
    out_queue: queue.Queue = attr.Factory(queue.Queue)
    heat: int = 0
    start_funcs: typing.ClassVar[list[str]] = []

    def running(self):
        """Returns whether this IRC connection is still up and running.

            >>> conn = IRCConnection('this.does.not.exist')
            >>> conn.running()
            False

        Returns:
            bool -- Self-explanatory.
        """

        return self._running and not self._stopping

    async def _cooldown(self):
        """
        This async loop is responsible for 'cooling' the backend
        down, at a specified frequency. It's part of the
        throttling mechanism.
        """

        if self.throttle:
            with self.new_stop_scope():
                while self.running():
                    self.heat = max(self.heat - 1, 0)

                    await trio.sleep(1 / self.cooldown_hertz)

    async def send(self, line: any):
        """
        Queues to send a backend-specific object.
        May be throttled. Despite being async, this function
        blocks, because it must emit the _SENT event.

        Arguments:
            line {str} -- The line to send.
        """

        waiting = [True]

        async def post_wait():
            waiting[0] = False

        self.out_queue.put((line, post_wait))

        with self.new_stop_scope():
            while waiting[0]:
                await trio.sleep(0.05)

    async def _sender(self):
        """
        This async loop is responsible for sending messages,
        handling throttling, and other similar things.
        """

        with self.new_stop_scope():
            while self.running():
                while not self.out_queue.empty():
                    if self.throttle:
                        self.heat += 1

                        if self.heat > self.max_heat:
                            break

                    item, on_send = self.out_queue.get()

                    await self._send(item)

                    if on_send:
                        await on_send()

                    await self.receive_message("_SENT", item)

                if self.running():
                    if self.heat > self.max_heat and self.throttle:
                        while self.heat:
                            await trio.sleep(0.2)

                    else:
                        await trio.sleep(0.05)

    async def _send(self, item: any):
        """Underlying method that sends a message through the Backend."""
        ...

    def maximum_heat(self) -> int:
        """
        The maximum value self.heat can reach before
        throttling commences.

        Defaults to self.max_heat.
        """

        return self.max_heat

    async def start(self):
        """
        Starts the backend.
        """

        connection = await trio.open_tcp_stream(self.host, self.port)

        if self.ssl_context:
            connection = trio.SSLStream(connection, self.ssl_context)

        self.connection = connection
        self._running = True

        async with trio.open_nursery() as nursery:

            async def _loaded_stop_scopes():
                nursery.start_soon(self._cooldown)
                nursery.start_soon(self._sender)

                for func_name in self.start_funcs:
                    nursery.start_soon(getattr(self, func_name))

                if self.auto_do_irc_handshake:
                    nursery.start_soon(self.send_irc_handshake)

            nursery.start_soon(self._watch_stop_scopes, _loaded_stop_scopes)

        self._running = False

    async def stop(self):
        """Asks this Backend to stop gracefully."""
        self._stopping = True

        for scope in self.stop_scopes:
            scope.cancel()

        await self.gracefully_close()

        while self.running():
            await trio.sleep(0.05)

        self._running = False
        self._stopping = False

    async def gracefully_close(self):
        """Perform graceful closure operations."""
        ...

    # Convenience decorators below.

    def when_running(f):
        """Decorator for a function that should run in 'while self.running'."""
        def _inner(self, *args, **kwargs):
            while self.running():
                f(*args, **kwargs)

        return _inner

    def stop_scope(f):
        """Decorator that wraps a function in a stop scope."""
        def _inner(self, *args, **kwargs):
            with self.new_stop_scope():
                f(*args, **kwargs)

        return _inner
