"""
The IRC backend. Use with great care, as IRC networks can be
rather rigid with client behavior, which includes throttling
(and is why throttling is by default enabled).
"""

import itertools as itt
import logging
import queue
import ssl
from collections import deque, namedtuple
from typing import Iterable, List, Optional, Set

import trio

from triarc.backend import DuplexBackend
from triarc.bot import Message


class IRCMessage(Message):
    def __init__(self, backend: "IRCConnection", line: str, origin: str, channel: str):
        super().__init__(
            backend,
            line,
            origin.split("!")[0],
            "!".join(origin.split("!")[1:]),
            channel,
            backend.host + "/" + channel,
        )

    def _split_size(self, line: str):
        while line:
            yield line[:300]
            line = line[300:]

    async def reply(self, reply_line: str, reply_reference: bool) -> bool:
        if self.channel == self.backend.nickname:
            await self.reply_privately(reply_line)

        else:
            await self.reply_channel(reply_line)

    async def reply_channel(self, reply_line: str, reply_reference: bool) -> bool:
        success = True

        if reply_reference:
            if not await self.backend.message(
                self.channel, "<{}> {}".format(self.author_name, self.line)
            ):
                success = False

        for line in self._split_size(reply_line):
            if not await self.backend.message(self.channel, line):
                success = False

        return success

    async def reply_privately(self, reply_line: str, reply_reference: bool) -> bool:
        success = True

        if reply_reference:
            if not await self.backend.message(
                self.channel, "<{}> {}".format(self.author_name, self.line)
            ):
                success = False

        for line in self._split_size(reply_line):
            if not await self.backend.message(self.channel, line):
                success = False

        return success


def irc_lex_response(resp: str) -> (str, str, str, bool, List[str], Optional[str]):
    if resp[0] == ":":
        resp = resp[1:]

    tokens = iter(resp.split(" "))

    origin = next(tokens)
    kind = next(tokens)

    if kind.isdigit() and len(kind) == 3:
        kind = int(kind)
        is_numeric = True

    else:
        is_numeric = False

    args = []
    data = []

    for tok in tokens:
        if data:
            data.append(" " + tok)

        elif tok[0] == ":":
            data.append(tok[1:])

        else:
            args.append(tok)

    dataline = "".join(data)
    del data

    return (resp, origin, kind, is_numeric, tuple(args), dataline)


class IRCParams:
    def __init__(self, args: Iterable[str], data: Optional[str] = None):
        self.args = tuple(args)
        self.data = data and str(data) or ""


class IRCResponse:
    def __init__(
        self,
        line: str,
        origin: str,
        is_numeric: int,
        kind: str,
        args: List[str],
        data: Optional[str] = None,
    ):
        self.line = line
        self.origin = origin
        self.is_numeric = is_numeric
        self.kind = kind
        self.params = IRCParams(args, data)

    def __repr__(self):
        return "IRCResponse({})".format(repr(self.line))

    @property
    def args(self):
        return self.params.args

    @property
    def data(self):
        return self.params.data

    @data.setter
    def data(self, value):
        self.params.data = value


def irc_parse_response(resp: str) -> IRCResponse:
    """Parses an IRC server response, according to RFC 1459.

        >>> irc_parse_response(':zirconium.libera.chat 404 :Not Found').kind
        404

        >>> print(irc_parse_response(':zirconium.libera.chat IS okay :a Good Word').args[0])
        okay

    Arguments:
        resp {str} -- The IRC response to parse.

    Returns:
        IRCResponse -- The parsed representation.
    """

    resp, origin, kind, is_numeric, args, data = irc_lex_response(resp)
    return IRCResponse(resp, origin, is_numeric, kind, args, data)


class IRCConnection(DuplexBackend):
    """An IRC connection. Used in order to create Triarc bots
    that function on IRC.
    """

    def __init__(
        self,
        host: str,
        port: int = 6667,
        nickname: str = "TriarcBot",
        realname: str = "The awesome Python comms bot framework",
        passw: str = None,
        nickserv_user: str = None,
        nickserv_pass: str = None,
        channels: Set[str] = (),
        pre_join_wait: float = 3.0,
        pre_login_wait: float = 5.0,
        cloaking_wait: float = 2.0,
        ssl_ctx: Optional[ssl.SSLContext] = None,
        auto_do_irc_handshake=True,
        **kwargs
    ):
        """Sets up an IRC connection that can be used as
        a triarc backend.

            >>> conn = IRCConnection('abcd')
            >>> conn._heat
            0
            >>> print(conn.ssl_context)
            None

            >>> import ssl
            >>> conn = IRCConnection('abcd', ssl_ctx=ssl.create_default_context())
            >>> conn.ssl_context is None
            False

        Arguments:
            host {str} -- The host of the IRC server.

        Keyword Arguments:
            port {int} -- The port of the IRC server. (default: 6667)

            nickname {str} -- The nickname used by this connection. {default: 'Triarc'}

            realname {str} --   The IRC 'real name' used by this connection.
                                (default: 'The awesome Python comms bot framework')

            passw {str} --  The IRC server password used by this connection, if any.
                            (default: None)

            nickserv_user {str} -- The NickServ username to identify to, if any. {default: None}
            nickserv_user {str} -- The NickServ password to identify with, if any. {default: None}

            channels {Set[str]} -- The channels to join after connecting. (default: ())

            pre_login_wait {float} -- The time to wait between sending the IRC handshake and
                                      authentication to NickServ. (default: 3.0)

            pre_join_wait {float} -- The time to wait between sending the IRC
                                     handshake and joining the first channels.
                                     Always happens after a NickServ authentication,
                                     if any, and accumulates with cloaking_wait. (default: 2.5)

            cloaking_wait {float} -- The additional delay between identifying to NickServ and
                                     autojoining listed channels. This delay is not awaited if
                                     there is no NickServ authentication. (default: 2.0)

            ssl_ctx {ssl.SSLContext} -- The SSL context used (or None if not using any).
                                        (default: None)

            auto_do_irc_handshake {bool} -- Whether to do the IRC handshake (i.e. initial
                                            commands, like USER, NICK, etc.) automatically
                                            when running the start method. (default: true)
        """

        super().__init__(**kwargs)

        self.host = host
        self.port = port
        self.ssl_context = ssl_ctx  # type: Optional[ssl.SSLContext]
        self.connection = None  # type: trio.SocketStream | trio.SSLStream

        self.nickname = nickname
        self.realname = realname
        self.passw = passw
        self.join_channels = set(channels)
        self.pre_join_wait = pre_join_wait
        self.pre_login_wait = pre_login_wait
        self.cloaking_wait = cloaking_wait

        self._running = False
        self._stopping = False

        self.auto_do_irc_handshake = auto_do_irc_handshake

        if nickserv_pass:
            self.nickserv = (nickserv_user, nickserv_pass)

        else:
            self.nickserv = None

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
        This async loop is responsible for 'cooling' the bot
        down, at a specified frequency. It's part of the
        throttling mechanism.
        """

        if self.throttle:
            with self.new_stop_scope():
                while self.running():
                    self._heat = max(self._heat - 1, 0)

                    await trio.sleep(1 / self.cooldown_hertz)

    async def send(self, line: str):
        """
        Queues to send a raw IRC command (string).
        May be throttled. This function
        blocks, because it must emit the _SENT event.

        Arguments:
            line {str} -- The line to send.
        """

        waiting = [True]

        async def post_wait():
            waiting[0] = False

        self._out_queue.put((line, post_wait))

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
                while not self._out_queue.empty():
                    if self.throttle:
                        self._heat += 1

                        if self._heat > self._max_heat:
                            break

                    item, on_send = self._out_queue.get()

                    await self._send(item)

                    if on_send:
                        await on_send()

                    await self.receive_message("_SENT", item)

                if self.running():
                    if self._heat > self._max_heat and self.throttle:
                        while self._heat:
                            await trio.sleep(0.2)

                    else:
                        await trio.sleep(0.05)

    async def _send(self, item: str):
        await self.connection.send_all(str(item).encode("utf-8") + b"\r\n")

    async def _receive(self, line: str):
        """
        This function is called asynchronously everytime
        the IRC backend receives a response from the
        remote host (server).

            >>> import trio
            >>> conn = IRCConnection('i.have.no.mouth.and.i.must.scream')
            ...
            >>> @conn.listen('IRC__NUMERIC')
            ... async def print_received(_, msg):
            ...     print(msg)
            ...
            >>> async def print_a_test():
            ...     print(await conn._receive(':skynet.ai 404 DEATH :AAAAAAAAA'))
            ...
            >>> trio.run(print_a_test)
            ...
            IRCResponse('skynet.ai 404 DEATH :AAAAAAAAA')
            True

        Arguments:
            line {str} --   A single line, after being extracted from received data, and
                            stripped of its trailing CRLF.

        Returns:
            bool -- Whether the line is valid IRC data.
        """

        await self.receive_message("_RAW", line)

        if line.split(" ")[0].upper() == "PING":
            data = " ".join(line.split(" ")[1:])
            await self.send("PONG " + data)

            return True

        response = irc_parse_response(line)

        if not response:
            return False

        if response.is_numeric:
            received_kind = "_NUMERIC"

        else:
            received_kind = response.kind

        await self.receive_message("IRC_" + received_kind, response)

        if not response.is_numeric and response.kind.upper() == "PRIVMSG":
            await self.receive_message(
                "MESSAGE",
                IRCMessage(
                    self, response.params.data, response.origin, response.params.args[0]
                ),
            )

        if received_kind.upper() == "PING":
            await self.send(
                "PONG {} :{}".format(" ".join(response.args), response.data)
            )

            return True

        return True

    async def _receiver(self):
        with self.new_stop_scope():
            while self.running():
                buf = ""

                try:
                    async for data in self.connection:
                        data = buf + data.decode("utf-8")

                        while "\n" in data:
                            line, data = data.split("\n", 1)

                            if line[-1] in "\r":
                                line = line[:-1]

                            await self._receive(line)

                        buf = data
                        await trio.sleep(0.05)

                except (trio.BrokenResourceError, trio.ClosedResourceError):
                    break

    async def send_irc_handshake(self):
        """
        Sends the IRC handshake, including
        nickname, real name, and optionally
        the server password.
        """

        with self.new_stop_scope():
            await self.send("NICK " + self.nickname.split(" ")[0])
            await self.send(
                "USER {} * * :{}".format(self.nickname.split(" ")[0], self.realname)
            )

            if self.passw:
                await self.send("PASS {}".format(self.passw))

            if self.nickserv:
                await trio.sleep(self.pre_login_wait)

                n_user, n_pass = self.nickserv
                await self.message(
                    "NickServ",
                    "IDENTIFY {}{}".format(" " + n_user if n_user else "", n_pass),
                )

                await trio.sleep(self.cloaking_wait)

            await trio.sleep(self.pre_join_wait)

            for chan in self.join_channels:
                await self.join(chan)

            # Prevent joining the same channels again (e.g. if the bot is
            # kicked/banned from them and send_irc_handshake is called again).
            self.join_channels = set()

    async def start(self):
        """
        Starts the IRC connection.
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
                nursery.start_soon(self._receiver)

                if self.auto_do_irc_handshake:
                    nursery.start_soon(self.send_irc_handshake)

            nursery.start_soon(self._watch_stop_scopes, _loaded_stop_scopes)

        self._running = False

    async def stop(self):
        self._stopping = True

        for scope in self.stop_scopes:
            scope.cancel()

        await self.connection.aclose()

        while self.running():
            await trio.sleep(0.05)

        self._running = False
        self._stopping = False

    # === IRC commands ===

    async def join(self, channel: str, chan_pass: Optional[str] = None):
        """Joins an IRC channel

        Arguments:
            channel {str} -- The name of the channel.

        Keyword Arguments:
            chan_pass {Optional[str]} -- An optional channel password. (default: {None})
        """

        if chan_pass:
            await self.send("JOIN {} :{}".format(channel, chan_pass))

        else:
            await self.send("JOIN {}".format(channel))

    async def leave(self, channel: str, reason: Optional[str] = None):
        """Leaves an IRC channel.

        Arguments:
            channel {str} -- The channel to leave.

        Keyword Arguments:
            reason {Optional[str]} --   The reason for which the channel has been left, if any.
                                        (default: {None})
        """

        if reason:
            await self.send("PART {} :{}".format(channel, reason))

        else:
            await self.send("PART {}".format(channel))

    async def message(self, target: str, message: str):
        """Sends a message to an IRC target (nickname or channel).

        Arguments:
            target {str} -- The IRC target. Can either be another client or a channel.
            message {str} -- The message.
        """

        await self.send(
            "PRIVMSG {} :{}".format(target, self._mutate_reply(target, message))
        )

    def message_sync(self, target: str, message: str):
        self._out_queue.put(("PRIVMSG {} :{}".format(target, message), None))
