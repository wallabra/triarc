"""
The Discord backend.
"""

from typing import Union, Callable

import time
import logging
import traceback
import queue
import warnings

import discord
import trio
import trio_asyncio

from triarc.backend import DuplexBackend
from triarc.bot import Message


class UnknownChannelWarning(warnings.UserWarning):
    pass


class DiscordMessage(Message):
    def __init__(self, backend, line, author, channel, discord_message):
        super().__init__(backend, line, author.name, author.id, '#' + getattr(channel, 'recipient', channel).name, channel.id)

        self.discord_author  = author
        self.discord_channel = channel
        self.discord_message = discord_message

    def _split_size(self, line):
        while line:
            yield line[:1900]
            line = line[1900:]

    async def reply(self, reply_line):
        for line in self._split_size(reply_line):
            await self.backend.message(self.discord_channel, line)

    async def reply_privately(self, reply_line):
        channel = self.discord_author.dm_channel or await self.discord_author.create_dm()

        for line in self._split_size(reply_line):
            await self.backend.message(channel, line)


class DiscordClient(DuplexBackend):
    """
    A Discord backend. Used in order to create Triarc bots
    that function on Discord.
    """

    def __init__(
        self,
        token: str,
        max_heat: int = 4,
        throttle: bool = True,
        cooldown_hertz: float = 1.2,
        min_send_interval: float = 0.25
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

            min_send_interval {float} --  The minimum amount of time, per second, between
                                          each sent message.

            throttle {bool} --  Whether to throttle. Do not disable unless you know what
                                you're doing. (default: True)

            cooldown_hertz {float} --   How many times per second throttle heat is cooled down.
                                        (Values exceeding max_heat, or by default 4, are always
                                        throttled!)
        """

        super().__init__()

        self._token = token
        self.nickname = None

        self._out_queue_in = None
        self._out_queue_out = None
        self._heat = 0
        self.max_heat = max_heat
        self.cooldown_hertz = cooldown_hertz
        self.throttle = throttle
        self._overheated = False
        self.min_send_interval = min_send_interval

        self._running = False
        self._stopping = False
        self._last_send_time = 0.0

        self.logger = None # type: logging.Logger

    def _setup_client(self, client: "discord.Client"):
        @client.event
        async def on_message(message: discord.message.Message):
            if message.author == client.user:
                return

            for line in message.content.split('\n'):
                await self.receive_message('MESSAGE', DiscordMessage(self, line, message.author, message.channel, message))

        @client.event
        async def on_ready():
            self.nickname = self.client.user.mention

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
        Deprecated and now unused.

        This async loop used to be responsible for 'cooling'
        the bot down, at a specified frequency. It used to
        be part of the throttling mechanism.
        """

        if self.throttle:
            with self.new_stop_scope():
                while self.running():
                    self._heat = max(self._heat - 1, 0)

                    await trio.sleep(1 / self.cooldown_hertz)

    async def send(self, line: Callable):
        """
        Queues a callback that is supposed to
        send a message or another event through the
        Discord client.

        May be throttled.

        Arguments:
            line {Callable} -- The callback to be executed
                               when sending.
        """

        await self._out_queue_in.send(line)

    def next_send_time(self):
        """
        Finds the next time where it will be acceptable
        to send another message, according to cooldown
        metrics.
        """

        base = self._last_send_time + self.min_send_interval

        if self._overheated:
            return base + self._heat / self.cooldown_hertz

        else:
            return base

    def heat_up(self):
        self._heat += 1

        if self._heat > self._max_heat:
            self._overheated = True

    def heat_down(self):
        self._heat -= 1

        if self._heat <= 0:
            self._heat = 0

            if self._overheated:
                self._overheated = False

    async def _sender(self):
        """
        This async loop is responsible for sending messages,
        handling throttling, and other similar things.
        """

        with self.new_stop_scope():
            while self.running():
                if self.throttle:
                    self.heat_up()
                    self._heat += 1

                    if self._heat > self._max_heat:
                        await trio.sleep(1.0 / self.cooldown_hertz)
                        self.heat_down()

                next_time = self.next_send_time()

                if next_time < time.time():
                    await trio.sleep(time.time() - next_time)

                callback = await self._out_queue_out.receive()
                await callback()

                self._last_send_time = time.time()

    def _message_callback(self, target: "discord.TextChannel", message: str):
        async def _inner():
            try:
                await trio_asyncio.aio_as_trio(target.send)(message)

            except discord.errors.Forbidden:
                traceback.print_exc()

            else:
                await self.receive_message('_SENT', message)

        return _inner

    def _message_embed_callback(self, target: "discord.TextChannel", embed: "discord.Embed"):
        async def _inner():
            try:
                await trio_asyncio.aio_as_trio(target.send)(embed=embed)

            except discord.errors.Forbidden:
                traceback.print_exc()

        return _inner

    def _resolve_target(self, target: Union[str, "discord.TextChannel"]) -> discord.TextChannel:
        """Resolves a target argument and ensures that a discord.TextChannel is returned."""
        if not hasattr(target, 'send'):
            # Most likely a str, even if a stringified int
            assert instanceof(target, str)

            orig = target # for error message purposes

            try:
                target = self.client.get_channel(int(target))

            except ValueError:
                raise ValueError("Invalid Discord channel ID passed: must be a numeric string, got {}".format(repr(orig)))

            if target is None:
                # chanenl not found
                warnings.warn(UnknownChannelWarning("Message target Discord channel ID {} does not exist or was not found".format(int(orig))))
                return None

        return target

    async def message(self, target: Union[str, "discord.TextChannel"], message: Union[str, "discord.Embed"], embed: bool = False):
        """Sends a message to a Discord target (nickname or discord.py channel object).

        Arguments:
            target {discord.TextChannel} -- The Discord target. Can be a channel object or a string ID.
            message {str} -- The message.
            embed {bool} -- If true, the message should be sent as a Discord embed rather than a string. https://discordpy.readthedocs.io/en/latest/api.html#embed
        """

        target = self._resolve_target(target)

        if target is None:
            return False

        if embed:
            await self.send(self._message_embed_callback(target, message))

        else:
            await self.send(self._message_callback(target, self._mutate_reply(target, message)))

        return True

    def message_sync(self, target: Union[str, "discord.TextChannel"], message: Union[str, "discord.Embed"], embed: bool = False) -> bool:
        target = self._resolve_target(target)

        if target is None:
            return False

        if embed:
            # WIP: mutate embeds as well
            self._out_queue.put(self._message_embed_callback(target, message))

        else:
            self._out_queue.put(self._message_callback(target, self._mutate_reply(target, message)))

        return True

    async def _trio_asyncio_start(self):
        self.client = discord.Client()

        self._setup_client(self.client)

        await self.client.login(self._token)
        await self.client.connect()

        self._running = False

    async def start(self):
        """Starts the Discord client."""

        self._running = True

        try:
            self._out_queue_in, self._out_queue_out = trio.open_memory_channel(0)

            async with trio.open_nursery() as nursery:
                async def _loaded_stop_scopes():
                    # nursery.start_soon(self._cooldown)
                    nursery.start_soon(self._sender)
                    nursery.start_soon(trio_asyncio.aio_as_trio(self._trio_asyncio_start))

                nursery.start_soon(self._watch_stop_scopes, _loaded_stop_scopes)

        finally:
            await self._out_queue_out.aclose()

            self._running = False

    async def stop(self):
        if not self.running():
            return False

        self._stopping = True

        for scope in self.stop_scopes:
            scope.cancel()

        await self.client.close()

        while self.running():
            await trio.sleep(0.05)

        self._running = False
        self._stopping = False

        return True

    def deinit(self):
        self._out_queue_in.aclose()
