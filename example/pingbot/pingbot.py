"""
Runs a very simple IRC bot that responds to the command ping.
"""

import trio_asyncio

from triarc.backend import Backend
from triarc.backends.irc import IRCConnection, IRCResponse
from triarc.backends.discord import DiscordClient
from triarc.bot import Bot



class MySimpleBot(Bot):
    """
    A very simple IRC and Discord bot that just responds to ping commands.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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

BOT = MySimpleBot("pingbot", [
    IRCConnection(host='irc.freenode.net', port=6667, channels=set(x.strip() for x in open('irc_channels.txt').read().strip().split('\n') if x and not x.lstrip().startswith('#')))
] + [
    DiscordClient(token.strip()) for token in set(open('dis_tokens.txt').read().strip().split('\n')) if token and not token.lstrip().startswith('#')
])
trio_asyncio.run(BOT.start)
