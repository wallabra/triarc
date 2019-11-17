import trio
import os
import snobeconfig as CFG
import praw

from triarc.bot import CommandBot
from triarc.backends.irc import IRCConnection, IRCResponse
from snobe import Snobe



class Grit(CommandBot):
    def __init__(self, *args, **kwargs):
        super().__init__(IRCConnection(*args, **kwargs), "'")

    async def respond(self, to: str, message: str):
        await self.backend.message(to, message)

    async def on_privmsg(self, resp: IRCResponse):
        if isinstance(resp, IRCResponse):
            rt = resp.params.args[0]

            if rt.upper() == self.backend.nickname.upper():
                target = resp.origin.split('!')[0]

            else:
                target = rt

            await self.read(target, resp.params.data)

    def init(self):
        @self.add_command('ping', 'Pong?')
        def define_ping(define, reply):
            @define
            async def ping(*args):
                await reply('Ye pong to "{}", yohohoh\'!'.format(' '.join(args)))

        snobe = Snobe(os.environ.get('BRAIN', 'cobe.brain'), client_id=CFG.client_id, client_secret=CFG.client_secret, password=CFG.password, user_agent=CFG.user_agent, username=CFG.username)
        reddit = snobe.reddit # type: praw.Reddit
        
        @self.add_command('ask', 'Asks the COBE chatbot a query.')
        def define_ask(define, reply):
            @define
            async def ask(*message):
                msg = ' '.join(message) or None

                await reply(snobe.brain.reply(msg, loop_ms=300)[:200].replace('\n', ' '))

        @self.add_command('learn', 'Tells the COBE chatbot to learn from some Subreddit.')
        def define_ask(define, reply):
            @define
            async def learn_from(subreddit, limit='30'):
                sr = reddit.subreddit(subreddit)

                for subm in sr.hot(limit=int(limit)):
                    snobe.check_learn(subm)

                await reply("Learned successfully.")

        # Log sent lines.
        @self.backend.listen('_SENT')
        async def on_sent_line(_, line):
            print('>>> ' + line)

        # Log received lines.
        @self.backend.listen('_RAW')
        async def on_raw(_, line):
            print('<<< ' + line)


if __name__ == '__main__':
    bot = Grit(host='irc.freenode.net', port=6667, channels=set(x.strip() for x in open("channels.txt").read().strip().split('\n')))
    trio.run(bot.start)