"""
The Discord backend.

Uses the high-level discord.py library for actually
communicating to Discord, unlike the IRC backend, which
is an IRC client in and of itself.

Also requires trio_asyncio, since Triarc uses trio (as
hinted in the name!), whereas discord.py uses asyncio,
requiring bridging in order to maintain proper, seamless
asynchronous functionality.
"""

# WIP: implement proxy objects; comply to triarc rewrite

import logging
import queue
import time
import traceback
import typing
import warnings
from typing import Callable, Optional, Union

import attr
import discord
import trio
import trio_asyncio

from ..backend import Backend
from ..bot import Message


class UnknownChannelWarning(UserWarning):
    pass


class DiscordMessage(Message):
    """A message received via the Discord backend."""

    def __init__(self, backend: str, line: str, discord_message: discord.Message):
        author, channel = discord_message.author, discord_message.channel

        super().__init__(
            backend,
            line,
            author.name,
            author.id,
            "#" + getattr(channel, "recipient", channel).name,
            str(channel.id),
            when=discord_message.created_at,
        )

        self.discord_author = author
        self.discord_channel = channel
        self.discord_message = discord_message

    def _split_size(self, line: str):
        while line:
            yield line[:1900]
            line = line[1900:]

    async def reply(self, reply_line: str, reply_reference: bool) -> bool:
        reply_reference = True
        success = True

        for line in self._split_size(reply_line):
            if not await self.backend.message(
                self.discord_channel,
                line,
                reference=self.discord_message if reply_reference else None,
            ):
                success = False

            reply_reference = False

        return success

    async def reply_channel(self, reply_line: str, reply_reference: bool) -> bool:
        await self.reply(reply_line, reply_reference)  # it's the same!

    async def reply_privately(self, reply_line: str, reply_reference: bool) -> bool:
        channel = (
            self.discord_author.dm_channel or await self.discord_author.create_dm()
        )
        success = True

        for line in self._split_size(reply_line):
            if not await self.backend.message(
                channel,
                line,
                reference=self.discord_message if reply_reference else None,
            ):
                success = False

            reply_reference = False

        return success


@attr.s(auto_attribs=True)
class DiscordClient(Backend):
    """
    A Discord backend. Used in order to create Triarc bots
    that function on Discord.
    """

    token: str
    nickname: typing.Optional[str] = None
    logger: typing.Optional[logging.Logger] = None
    out_queue_in: typing.Optional[trio.MemorySendChannel] = None
    out_queue_out: typing.Optional[trio.MemoryReceiveChannel] = None

    def _setup_client(self, client: "discord.Client"):
        @client.event
        async def on_message(message: discord.message.Message):
            if message.author == client.user:
                return

            for line in message.content.split("\n"):
                await self.receive_message(
                    "MESSAGE", DiscordMessage(self, line, message)
                )

        @client.event
        async def on_ready():
            self.nickname = self.client.user.mention

    def _message_callback(
        self,
        target: "discord.TextChannel",
        message: str,
        reference: Optional[Union[discord.Message, discord.MessageReference]] = None,
    ):
        async def _inner():
            try:
                await trio_asyncio.aio_as_trio(target.send)(
                    message, reference=reference
                )

            except discord.errors.Forbidden:
                traceback.print_exc()

            else:
                await self.receive_message("_SENT", message)

        return _inner

    def _message_embed_callback(
        self,
        target: "discord.TextChannel",
        embed: "discord.Embed",
        reference: Optional[Union[discord.Message, discord.MessageReference]] = None,
    ):
        async def _inner():
            try:
                await trio_asyncio.aio_as_trio(target.send)(
                    embed=embed, reference=reference
                )

            except discord.errors.Forbidden:
                traceback.print_exc()

            else:
                await self.receive_message("_SENT", embed.description)

        return _inner

    def _resolve_target(
        self, target: Union[str, "discord.TextChannel"]
    ) -> discord.TextChannel:
        """Resolves a target argument and ensures that a discord.TextChannel is returned."""
        if not hasattr(target, "send"):
            # Most likely a str, even if a stringified int
            assert isinstance(target, str)

            orig = target  # for error message purposes

            try:
                target = self.client.get_channel(int(target))

            except ValueError:
                raise ValueError(
                    "Invalid Discord channel ID passed: must be a numeric string, got {}".format(
                        repr(orig)
                    )
                )

            if target is None:
                # chanenl not found
                warnings.warn(
                    UnknownChannelWarning(
                        "Message target Discord channel ID {} does not exist or was not found".format(
                            int(orig)
                        )
                    )
                )
                return None

        return target

    def _mutate_embed(self, target: discord.TextChannel, message: discord.Embed):
        """Mutate a Discord embed by the same mutators governing text replies."""

        channel_id = str(target.id)

        # Mutate the embed's description.

        if message.description.strip():
            message.description = "\n".join(
                self._mutate_reply(channel_id, line)
                for line in message.description.split("\n")
            )

        # Mutate the embed's fields.

        for field in message.fields:
            field.value = "\n".join(
                self._mutate_reply(channel_id, line) for line in field.value.split("\n")
            )

    async def message(
        self,
        target: Union[str, "discord.TextChannel"],
        message: Union[str, "discord.Embed"],
        embed: bool = False,
        reference: Optional[Union[discord.Message, discord.MessageReference]] = None,
    ):
        """Sends a message to a Discord target (nickname or discord.py channel object).

        Arguments:
            target {discord.TextChannel} -- The Discord target. Can be a channel object or a string ID.
            message {str} -- The message.
            embed {bool} -- If true, the message should be sent as a Discord embed rather than a string. https://discordpy.readthedocs.io/en/latest/api.html#embed
            reference {Optional[Union[discord.Message, discord.MessageReference]]} -- If not None, a message to be referred to as in a reply.
        """

        target = self._resolve_target(target)

        if target is None:
            return False

        if embed:
            self._mutate_embed(target, message)
            await self.send(
                self._message_embed_callback(target, message, reference=reference)
            )

        else:
            await self.send(
                self._message_callback(
                    target,
                    self._mutate_reply(str(target.id), message),
                    reference=reference,
                )
            )

        return True

    def message_sync(
        self,
        target: Union[str, "discord.TextChannel"],
        message: Union[str, "discord.Embed"],
        embed: bool = False,
        reference: Optional[Union[discord.Message, discord.MessageReference]] = None,
    ) -> bool:
        target = self._resolve_target(target)

        if target is None:
            return False

        if embed:
            self._mutate_embed(target, message)
            self.out_queue_in.send(
                self._message_embed_callback(target, message, reference=reference)
            )

        else:
            self.out_queue_in.send(
                self._message_callback(
                    target,
                    self._mutate_reply(str(target.id), message),
                    reference=reference,
                )
            )

        return True

    async def _trio_asyncio_start(self):
        self.client = discord.Client()

        self._setup_client(self.client)

        await self.client.login(self.token)
        await self.client.connect()

        self._running = False

    async def start(self):
        """Starts the Discord client."""

        if self._stopping:
            raise RuntimeError("Tried to start a backend whilst it is stopping!")

        self._running = True

        try:
            self.out_queue_in, self.out_queue_out = trio.open_memory_channel(0)

            async with trio.open_nursery() as nursery:

                async def _loaded_stop_scopes():
                    nursery.start_soon(self._sender)
                    nursery.start_soon(
                        trio_asyncio.aio_as_trio(self._trio_asyncio_start)
                    )

                nursery.start_soon(self._watch_stop_scopes, _loaded_stop_scopes)

        finally:
            await self.out_queue_out.aclose()

            self._running = False

    @when_running
    @stop_scope
    async def _sender(self):
        callback = await self.out_queue_out.receive()
        await callback()

        trio.sleep(0.1)

    async def stop(self):
        if not self.running:
            return False

        self._stopping = True

        for scope in self.stop_scopes:
            scope.cancel()

        await self.client.close()

        while self.running:
            await trio.sleep(0.1)

        self._running = False
        self._stopping = False

        return True
