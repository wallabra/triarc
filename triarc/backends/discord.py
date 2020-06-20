"""
The Discord backend.
"""

from typing import Union, Callable

import logging
import traceback
import queue

import discord
import trio
import trio_asyncio

from triarc.backend import DuplexBackend
from triarc.bot import Message


class DiscordMessage(Message):
    def __init__(self, backend, line, author, channel, discord_message):
        super().__init__(backend, line, author.name, author.id, '#' + channel.name, channel.id)

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
        for line in self._split_size(reply_line):   
            await self.backend.message(self.discord_author.channel, line)


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
        self.nickname = None

        self._out_queue = queue.Queue()
        self._heat = 0
        self.max_heat = max_heat
        self.cooldown_hertz = cooldown_hertz
        self.throttle = throttle

        self._running = False
        self._stopping = False

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
        This async loop is responsible for 'cooling' the bot
        down, at a specified frequency. It's part of the
        throttling mechanism.
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

        self._out_queue.put(line)

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

                    callback = self._out_queue.get()

                    await callback()

                if self.running():
                    if self._heat > self.max_heat and self.throttle:
                        while self._heat:
                            await trio.sleep(0.2)

                    else:
                        await trio.sleep(0.05)

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
            await self.send(self._message_callback(target, self._mutate_reply(target, message)))

    def message_sync(self, target: "discord.TextChannel", message: Union[str, "discord.Embed"], embed: bool = False):
        if embed:
            self._out_queue.put(self._message_embed_callback(target, message))

        else:
            self._out_queue.put(self._message_callback(target, self._mutate_reply(target, message)))

    async def _trio_asyncio_start(self):
        self.client = discord.Client()

        self._setup_client(self.client)

        await self.client.login(self._token)
        await self.client.connect()

        self._running = False

    async def start(self):
        """Starts the Discord client."""

        self._running = True

        async with trio.open_nursery() as nursery:
            async def _loaded_stop_scopes():
                nursery.start_soon(trio_asyncio.aio_as_trio(self._trio_asyncio_start))
                nursery.start_soon(self._cooldown)
                nursery.start_soon(self._sender)

            nursery.start_soon(self._watch_stop_scopes, _loaded_stop_scopes)

        self._running = False

    async def stop(self):
        self._stopping = True

        for scope in self.stop_scopes:
            scope.cancel()

        await self.client.close()

        while self.running():
            await trio.sleep(0.05)

        self._running = False
        self._stopping = False
