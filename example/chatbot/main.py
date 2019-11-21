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

            await self.read(target, resp.params.data, resp)

    def init(self):
        @self.add_command('ping', 'Pong?')
        def define_ping(define, reply):
            @define
            async def ping(R, *args):
                await reply('Ye pong to "{}", yohohoh\'!'.format(' '.join(args)))

        snobe = Snobe(os.environ.get('BRAIN', 'cobe.brain'), client_id=CFG.client_id, client_secret=CFG.client_secret, password=CFG.password, user_agent=CFG.user_agent, username=CFG.username)
        reddit = snobe.reddit # type: praw.Reddit
        
        @self.add_command('ask', 'Asks the COBE chatbot a query.')
        def define_ask(define, reply, loop_ms=300):
            @define
            async def ask(R, *message):
                msg = ' '.join(message) or None

                await reply(snobe.brain.reply(msg, loop_ms=loop_ms)[:200].replace('\n', ' '))

        @self.add_command('learnsub', 'Tells the COBE chatbot to learn from some Subreddit.')
        def define_sub_learn(define, reply):
            @define
            async def learn_from(R, subreddit, limit='30'):
                sr = reddit.subreddit(subreddit)

                if sr:
                    for subm in sr.hot(limit=int(limit)):
                        snobe.learn(subm)
    
                    await reply("Learned successfully.")

                else:
                    await reply("Error: no such subreddit!")

        @self.add_command('learnpost', 'Tells the COBE chatbot to learn from a single submission.')
        def define_learn(define, reply):
            @define
            async def learn_post(R, arg):
                subm = reddit.submission(url=arg)

                if subm:
                    snobe.check_learn(subm)
                    await reply("Learned successfully.")

                else:
                    await reply("Error: no such submission!")

        @self.add_command('learncom', 'Tells the COBE chatbot to learn from a single comment.')
        def define_learn_one(define, reply):
            @define
            async def learn_one(R, arg):
                comm = reddit.comment(url=arg)

                if comm:
                    snobe.check_learn(comm)
                    await reply("Learned successfully.")

                else:
                    await reply("Error: no such comment!")

        # Log sent lines.
        @self.backend.listen('_SENT')
        async def on_sent_line(_, line):
            print('>>> ' + line)

        # Log received lines.
        @self.backend.listen('_RAW')
        async def on_raw(_, line):
            print('<<< ' + line)


if __name__ == '__main__':
    bot = Grit(host='irc.freenode.net', port=6667, nickname='GritBot', channels=set(x.strip() for x in open("channels.txt").read().strip().split('\n')))
    trio.run(bot.start)