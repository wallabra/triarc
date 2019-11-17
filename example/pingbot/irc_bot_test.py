import trio

from triarc.backends.irc import IRCConnection, IRCResponse
from triarc.bot import Bot



class MySimpleIRCBot(Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(IRCConnection(*args, **kwargs))

    def init(self):
        self.ping_message = "Fifteen pirates on a dead man's chest! Yohoho and a bottle of rum!"

        @self.backend.listen('_SENT')
        async def on_sent_line(_, line):
            print('>>> ' + line)

    async def on_privmsg(self, resp: IRCResponse):
        if isinstance(resp, IRCResponse):
            sender = resp.origin.split('!')[0]
            target = resp.params.args[0]
            message = resp.params.data.strip()

            if message == '\'ping':
                pong = '[pong] ' + self.ping_message

                if target == self.backend.nickname:
                    await self.backend.message(sender, pong)

                else:
                    await self.backend.message(target, pong)

    async def on_raw(self, _, line: str):
        print('<<< ' + line)

bot = MySimpleIRCBot(host='irc.freenode.net', port=6667, channels=set(open('channels.txt').read().split('\n')))
trio.run(bot.start)