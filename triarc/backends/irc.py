"""
The IRC backend. Use with great care, as IRC networks can be
rather rigid with client behavior, which includes throttling
(and is why throttling is by default enabled).
"""

import re
import queue
import ssl

from typing import Optional, Set
from collections import namedtuple

import trio

from triarc.backend import Backend




IRC_SOFT_NEWLINE = re.compile(r'\r?\n')

IRC_RESP_PREFIX = r':([^ \0]+) '
IRC_RESP_NUMERIC = r'([0-9]{3})'
IRC_RESP_COMMAND = r'([^ \0]+)'
IRC_RESP_PARAMS = r'((?: (?:[^\0 \n]*))*?)?(?: :([^\0\n]*))?'

IRC_RESP = '^{}(?:(?:{})|(?:{})){}$'.format(
    IRC_RESP_PREFIX,
    IRC_RESP_NUMERIC,
    IRC_RESP_COMMAND,
    IRC_RESP_PARAMS
)

IRC_RESP = re.compile(IRC_RESP)


IRCResponse = namedtuple('IRCResponse', (
    'line',
    'origin',
    'is_numeric',
    'kind',
    'params'
))

IRCParams = namedtuple('IRCParams', (
    'args',
    'data'
))

def irc_parse_response(resp: str) -> IRCResponse:
    """Parses an IRC server response, according to RFC 1459.

        >>> irc_parse_response(':adams.freenode.net 404 :Not Found')
        IRCResponse(line=':adams.freenode.net 404 :Not Found', \
origin='adams.freenode.net', is_numeric=True, kind='404', params=IRCParams(args=[''], \
data='Not Found'))

        >>> irc_parse_response(':adams.freenode.net IS okay :a Good Word')
        IRCResponse(line=':adams.freenode.net IS okay :a Good Word', \
origin='adams.freenode.net', is_numeric=False, kind='IS', params=IRCParams(args=['okay'], \
data='a Good Word'))

    Arguments:
        resp {str} -- The IRC response to parse.

    Returns:
        IRCResponse -- The parsed representation.
    """

    resp = IRC_RESP.match(resp)

    if not resp:
        return None

    if resp.group(2):
        is_numeric = True
        kind = resp.group(2)

    else:
        is_numeric = False
        kind = resp.group(3)

    args = resp.group(4).strip().split(' ')
    data = resp.group(5)

    params = IRCParams(args, data)
    return IRCResponse(resp.group(0), resp.group(1), is_numeric, kind, params)


class IRCConnection(Backend):
    """An IRC connection. Used in order to create Triarc bots
    that function on IRC.
    """

    def __init__(
            self,
            host: str,
            port: int = 6667,
            nickname: str = 'TriarcBot',
            realname: str = 'The awesome Python comms bot framework',
            passw: str = None,
            channels: Set[str] = (),
            pre_join_wait: float = 5.,
            max_heat: int = 4,
            ssl_ctx: Optional[ssl.SSLContext] = None,
            throttle: bool = True,
            cooldown_hertz: float = 1.2,
            auto_do_irc_handshake=True
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

            channels {Set[str]} -- The channels to join after connecting. (default: ())

            pre_join_wait {float} --    The time to wait between sending the IRC
                                         handshake and joining the first channels. (default: 4)

            max_heat {int} --   The maximum 'heat' (messaging spree) before
                                outgoing data is throttled. (default: 4)

            ssl {ssl.SSLContext} -- The SSL context used (or None if not using any).
                                    (default: None)

            throttle {bool} --  Whether to throttle. Do not disable unless you know what
                                you're doing. (default: True)

            cooldown_hertz {float} --   How many times per second throttle heat is cooled down.
                                        (Values exceeding max_heat, or by default 4, are always
                                        throttled!)

            auto_do_irc_handshake {bool} -- Whether to do the IRC handshake (i.e. initial
                                            commands, like USER, NICK, etc.) automatically
                                            when running the start method. (default: true)
        """

        super().__init__()

        self.host = host
        self.port = port
        self.ssl_context = ssl_ctx # type: Optional[ssl.SSLContext]
        self.connection = None # type: trio.SocketStream | trio.SSLStream

        self.nickname = nickname
        self.realname = realname
        self.passw = passw
        self.join_channels = set(channels)
        self.pre_join_wait = pre_join_wait

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

        self.auto_do_irc_handshake = auto_do_irc_handshake

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

    def _send(self, line: str):
        self._out_queue.put((line, None))

    async def send(self, line: str):
        """
        Queues to send a raw IRC command (string).
        May be throttled. If awaited, this function
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

    async def _send(self, item: str):
        await self.connection.send_all(str(item).encode('utf-8') + b'\r\n')

    async def _receive(self, line: str):
        """
        This function is called asynchronously everytime
        the IRC backend receives a response from the
        remote host (server).

            >>> import trio
            >>> conn = IRCConnection('i.have.no.mouth.and.i.must.scream')
            ...
            >>> @conn.listen('_NUMERIC')
            ... async def print_received(_, msg):
            ...     print(msg)
            ...
            >>> async def print_a_test():
            ...     print(await conn._receive(':skynet.ai 404 DEATH :AAAAAAAAA'))
            ...
            >>> trio.run(print_a_test)
            ...
            IRCResponse(line=':skynet.ai 404 DEATH :AAAAAAAAA', 'skynet.ai', \
is_numeric=True, kind='404', params=IRCParams(args=['DEATH'], data='AAAAAAAAA'))
            True

        Arguments:
            line {str} --   A single line, after being extracted from received data, and
                            stripped of its trailing CRLF.

        Returns:
            bool -- Whether the line is valid IRC data.
        """

        await self.receive_message('_RAW', line)

        response = irc_parse_response(line)

        if not response:
            if line.split(' ')[0].upper() == 'PING':
                data = ' '.join(line.split(' ')[1:])
                await self.send('PONG ' + data)

                return True

            return False

        if response.is_numeric:
            received_kind = '_NUMERIC'

        else:
            received_kind = response.kind

        await self.receive_message(received_kind, response)
        return True

    async def _receiver(self):
        with self.new_stop_scope():
            while self.running():
                buffer = ''

                try:
                    async for data in self.connection:
                        lines = re.split(IRC_SOFT_NEWLINE, buffer + data.decode('utf-8'))
                        buffer = lines.pop()

                        for line in lines:
                            await self._receive(line)

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
            if self.passw:
                await self.send('PASS {}'.format(self.passw))

            await self.send('NICK ' + self.nickname.split(' ')[0])
            await self.send('USER {} * * :{}'.format(self.nickname.split(' ')[0], self.realname))
            await trio.sleep(self.pre_join_wait)

            for chan in self.join_channels:
                await self.join(chan)

            # Prevent joining the same channels again (e.g. if the bot is
            # kicked/banned from them and send_irc_handshake is called again).
            self.join_channels = set()

    async def _watch_stop_scopes(self, on_loaded):
        async with trio.open_nursery() as nursery:
            self.stop_scope_watcher = nursery

            async def _run_until_stopped():
                while self.running():
                    await trio.sleep(0.05)

            nursery.start_soon(_run_until_stopped)
            nursery.start_soon(on_loaded)

    async def start(self):
        """Starts the IRC connection.

            >>> import trio
            >>> import re
            ...
            >>> from typing import Union
            >>> from triarc.backends.irc import IRCConnection, IRC_SOFT_NEWLINE
            ...
            ...
            ...
            >>> PORT = 51523
            ...
            >>> def make_mock_irc_server(cancel_scope: trio.CancelScope):
            ...     async def mock_irc_server(client: Union[trio.SocketStream, trio.SSLStream]):
            ...         buffer = ""
            ...
            ...         try:
            ...             async for data in client:
            ...                 lines = re.split(
            ...                     IRC_SOFT_NEWLINE, buffer + data.decode('utf-8')
            ...                 )
            ...                 buffer = lines.pop()
            ...
            ...                 stop = False
            ...
            ...                 for l in lines:
            ...                     if l == '::STOP!':
            ...                         await client.send_all(
            ...                             ':mock.server DONE\\r\\n'.encode('utf-8')
            ...                         )
            ...                         await client.aclose()
            ...                         stop = True
            ...
            ...                     else:
            ...                         await client.send_all(
            ...                             ':mock.server ECHO :{}\\r\\n'.format(l)
            ...                                 .encode('utf-8')
            ...                         )
            ...
            ...                 if stop:
            ...                     await cancel_scope.cancel()
            ...                     break
            ...
            ...         except trio.BrokenResourceError:
            ...             return
            ...
            ...     return mock_irc_server
            ...
            >>> async def test_irc_server():
            ...     scope = trio.CancelScope()
            ...
            ...     with scope as status:
            ...         await trio.serve_tcp(make_mock_irc_server(scope), PORT)
            ...
            >>> async def test_irc_client(nursery):
            ...     client = IRCConnection('127.0.0.1', PORT)
            ...
            ...     @client.listen_all()
            ...     async def on_message(_, msg):
            ...         print(msg.line)
            ...
            ...     @client.listen('DONE')
            ...     async def on_done(_, msg):
            ...         await client.stop()
            ...
            ...     async def do_client_things():
            ...         await trio.sleep(0.05)
            ...         await client.send_irc_handshake()
            ...         await client.send('AAA')
            ...         await client.send('::STOP!')
            ...
            ...         return
            ...
            ...     async with trio.open_nursery() as new_nursery:
            ...         new_nursery.start_soon(client.start)
            ...         new_nursery.start_soon(do_client_things)
            ...
            >>> async def run_test():
            ...     async with trio.open_nursery() as nursery:
            ...         nursery.start_soon(test_irc_server)
            ...         nursery.start_soon(test_irc_client, nursery)
            ...
            >>> trio.run(run_test)
            ...
            :mock.server ECHO :NICK Triarc
            :mock.server ECHO :USER Triarc * * :The awesome Python comms bot framework
            :mock.server ECHO :AAA
            :mock.server DONE
        """

        connection = await trio.open_tcp_stream(self.host, self.port)

        if self.ssl_context:
            connection = trio.SSLStream(connection, self.ssl_context)

        self.connection = connection
        self._running = True

        if self.auto_do_irc_handshake:
            async with trio.open_nursery() as nursery:
                async def _loaded_stop_scopes():
                    nursery.start_soon(self._cooldown)
                    nursery.start_soon(self._sender)
                    nursery.start_soon(self._receiver)
                    nursery.start_soon(self.send_irc_handshake)

                nursery.start_soon(self._watch_stop_scopes, _loaded_stop_scopes)

        self._running = False

    async def stop(self):
        self._stopping = True
        await self.connection.aclose()

        for scope in self.stop_scopes:
            scope.cancel()

        while self.running():
            await trio.sleep(0.05)

        self._running = False
        self._stopping = False

    #=== IRC commands ===

    async def join(self, channel: str, chan_pass: Optional[str] = None):
        """Joins an IRC channel

        Arguments:
            channel {str} -- The name of the channel.

        Keyword Arguments:
            chan_pass {Optional[str]} -- An optional channel password. (default: {None})
        """

        if chan_pass:
            await self.send('JOIN {} :{}'.format(channel, chan_pass))

        else:
            await self.send('JOIN {}'.format(channel))

    async def leave(self, channel: str, reason: Optional[str] = None):
        """Leaves an IRC channel.

        Arguments:
            channel {str} -- The channel to leave.

        Keyword Arguments:
            reason {Optional[str]} --   The reason for which the channel has been left, if any.
                                        (default: {None})
        """

        if reason:
            await self.send('PART {} :{}'.format(channel, reason))

        else:
            await self.send('PART {}'.format(channel))

    async def message(self, target: str, message: str):
        """Sends a message to an IRC target (nickname or channel).

        Arguments:
            target {str} -- The IRC target. Can either be another client or a channel.
            message {str} -- The message.
        """

        await self.send('PRIVMSG {} :{}'.format(target, message))

    def message_sync(self, target: str, message: str):
        self._out_queue.put(('PRIVMSG {} :{}'.format(target, message), None))