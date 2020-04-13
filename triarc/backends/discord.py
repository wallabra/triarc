"""
The Discord backend.
"""

from typing import Union, Callable

import logging
import queue

import discord
import trio
import trio_asyncio
import triarc

from triarc.backend import Backend




class DiscordClient(Backend):
    """
    A Discord backend. Used in order to create Triarc bots
    that function on Discord.
    """

    def __init__(
        self,
        token: str,
        max_heat: int = 4,
        throttle: bool = True,
        cooldown_hertz: float = 1.2
    ):
        """
        Prepares a Discord bot session, via the
        discord.py library, which can be used as
        a triarc backend.

        Arguments:
            token {str} -- The token of your bot.

        Keyword Arguments:
            max_heat {int} --   The maximum 'heat' (messaging spree) before
                                outgoing data is throttled. (default: 4)

            throttle {bool} --  Whether to throttle. Do not disable unless you know what
                                you're doing. (default: True)

            cooldown_hertz {float} --   How many times per second throttle heat is cooled down.
                                        (Values exceeding max_heat, or by default 4, are always
                                        throttled!)
        """

        super().__init__()

        self._token = token
        self.client = discord.Client()

        self._out_queue = queue.Queue()
        self._heat = 0
        self.max_heat = max_heat
        self.cooldown_hertz = cooldown_hertz
        self.throttle = throttle

        self._running = False
        self._stopping = False

        self.logger = None # type: logging.Logger
        self.stop_scopes = set()
        self.stop_scope_watcher = None # type: trio.NurseryManager

        self._setup_client(self.client)

    def _setup_client(self, client: "discord.Client"):
        @client.event
        async def on_message(message):
            if message.author == client.user:
                return

            await self.receive_message('MESSAGE', message)

    def listen(self, name: str = '_'):
        """Adds a listener for specific messages received in this backend.
        Use as a decorator generating method.

        Keyword Arguments:
            name {str} -- The name of the event to listen for (default: {'_'})

        Returns:
            function -- The decorator method.
        """

        def _decorator(func):
            self._listeners.setdefault(name, set()).add(func)
            return func

        return _decorator

    def listen_all(self):
        """Adds a listener for all messages received in this backend.
        Use as a decorator generating method.

        Returns:
            function -- The decorator method.
        """

        def _decorator(func):
            self._global_listeners.add(func)
            return func

        return _decorator

    def running(self):
        """Returns whether this client is still up and running.

        Returns:
            bool -- Self-explanatory.
        """

        return self._running and not self._stopping

    async def _cooldown(self):
        """
        This async loop is responsible for 'cooling' the bot
        down, at a specified frequency. It's part of the
        throttling mechanism.
        """

        if self.throttle:
            with self.new_stop_scope():
                while self.running():
                    self._heat = max(self._heat - 1, 0)

                    await trio.sleep(1 / self.cooldown_hertz)

    async def _send(self, item: Callable):
        await item.callback()

    async def send(self, line: Callable):
        """
        Queues a callback that is supposed to
        send a message or another event through the
        Discord client.

        May be throttled. This function
        blocks, because it must emit the _SENT event.

        Arguments:
            line {Callable} -- The callback to be executed
                               when sending.
        """

        waiting = [True]

        async def post_wait():
            waiting[0] = False

        self._out_queue.put((line, post_wait))

        with self.new_stop_scope():
            while waiting[0]:
                await trio.sleep(0.05)

    def new_stop_scope(self):
        """Makes a new Trio cancel scope, which is automatically
        cancelled when the backend is stopped. The backend must
        be running.

        Raises:
            RuntimeError: Tried to make a stop scope while the backend isn't running.

        Returns:
            trio.CancelScope -- The stop scope.
        """
        scope = trio.CancelScope()
        self.stop_scopes.add(scope)

        if self.stop_scope_watcher:
            async def watch_scope(scope):
                while not scope.cancel_called:
                    await trio.sleep(0.05)

                self.stop_scopes.remove(scope)
                del scope

            self.stop_scope_watcher.start_soon(watch_scope, scope)

        else:
            raise RuntimeError("Tried to obtain a stop scope while the backend isn't running!")

        return scope

    async def _sender(self):
        """
        This async loop is responsible for sending messages,
        handling throttling, and other similar things.
        """

        with self.new_stop_scope():
            while self.running():
                while not self._out_queue.empty():
                    if self.throttle:
                        self._heat += 1

                        if self._heat > self.max_heat:
                            break

                    item, on_send = self._out_queue.get()

                    await self._send(item)

                    if on_send:
                        await on_send()

                    await self.receive_message('_SENT', item)

                if self.running():
                    if self._heat > self.max_heat and self.throttle:
                        while self._heat:
                            await trio.sleep(0.2)

                    else:
                        await trio.sleep(0.05)

    def _message_callback(self, target: "discord.TextChannel", message: str):
        return lambda: target.send(message)

    def _message_embed_callback(self, target: "discord.TextChannel", embed: "discord.Embed"):
        return lambda: target.send(embed=embed)

    async def message(self, target: "discord.TextChannel", message: Union[str, "discord.Embed"], embed: bool = False):
        """Sends a message to a Discord target (nickname or discord.py channel object).

        Arguments:
            target {discord.TextChannel} -- The Discord target. Is a channel object.
            message {str} -- The message.
            embed {bool} -- If true, the message should be sent as a Discord embed rather than a string. https://discordpy.readthedocs.io/en/latest/api.html#embed
        """

        if embed:
            await self.send(self._message_embed_callback(target, message))

        else:
            await self.send(self._message_callback(target, message))

    def message_sync(self, target: "discord.TextChannel", message: Union[str, "discord.Embed"], embed: bool = False):
        if embed:
            self._out_queue.put(self._message_embed_callback(target, message))

        else:
            self._out_queue.put(self._message_callback(target, message))

        #trio_asyncio

    async def _watch_stop_scopes(self, on_loaded):
        async with trio.open_nursery() as nursery:
            self.stop_scope_watcher = nursery

            async def _run_until_stopped():
                while self.running():
                    await trio.sleep(0.05)

            nursery.start_soon(_run_until_stopped)
            nursery.start_soon(on_loaded)

    async def start(self):
        """Starts the Discord client."""
        await trio_asyncio.aio_as_trio(self.client.start)(self._token)

    async def stop(self):
        self._stopping = True

        for scope in self.stop_scopes:
            scope.cancel()

        await self.client.close()

        while self.running():
            await trio.sleep(0.05)

        self._running = False
        self._stopping = False

    def post_bot_register(self, bot: "triarc.bot.Bot"):
        bot.add_alias('message', 'privmsg')
