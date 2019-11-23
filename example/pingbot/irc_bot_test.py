"""
Runs a very simple IRC bot that responds to the command ping.
"""

import trio

from triarc.backend import Backend
from triarc.backends.irc import IRCConnection, IRCResponse
from triarc.bot import Bot



class MySimpleIRCBot(Bot):
    """
    A very simple IRC bot that just responds to ping commands.
    """

    def __init__(self, *args, **kwargs):
        super().__init__({IRCConnection(*args, **kwargs)})

        self.ping_message = "Fifteen pirates on a dead man's chest! Yohoho and a bottle of rum!"

    async def on_privmsg(self, which: Backend, resp: IRCResponse):
        """Checks all received messages for the ping command.

        Arguments:
            which {Backend} -- The backend responsible for the PRIVMSG.
            resp {IRCResponse} -- The backend response to check.
        """

        if isinstance(resp, IRCResponse):
            sender = resp.origin.split('!')[0]
            target = resp.params.args[0]
            message = resp.params.data.strip()

            if message == '\'ping':
                pong = '[pong] ' + self.ping_message

                if target == which.nickname:
                    await which.message(sender, pong)

                else:
                    await which.message(target, pong)

BOT = MySimpleIRCBot(
    host='irc.freenode.net', port=6667, channels=set(open('channels.txt').read().split('\n'))
)
trio.run(BOT.start)
