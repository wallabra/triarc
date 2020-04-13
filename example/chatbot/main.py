"""Grit is the advanced IRC chat bot. It can learn from Reddit, and
uses the COBE 2 library to provide users with the most entertaining
chatbot experience anywhere on IRC."""

import os
import re

import trio_asyncio

import snobeconfig as CFG
from triarc.bot import CommandBot
from triarc.backend import Backend
from triarc.backends.irc import IRCConnection, IRCResponse
from triarc.mutators.antihilite import AntiHilite
from snobe import Snobe



class Grit(CommandBot):
    """Runs Grit, the advanced IRC chatbot."""

    def __init__(self, *args, name="grit", **kwargs):
        super().__init__(name, {IRCConnection(*args, **kwargs)})

        self.snobe = Snobe(
            os.environ.get('BRAIN', 'cobe.brain'),
            client_id=CFG.CLIENT_ID,
            client_secret=CFG.CLIENT_SECRET,
            password=CFG.PASSWORD,
            user_agent=CFG.USER_AGENT,
            username=CFG.USERNAME
        )

    async def on_privmsg(self, which: Backend, resp: IRCResponse):
        """This method is called by Bot when it receives
        events from the IRCConnection backend. It is used
        in order to use the CommandBot.read method.

        Arguments:
            resp {IRCResponse} -- The IRC backend's response object.
        """

        if isinstance(resp, IRCResponse):
            resp_target = resp.params.args[0]

            if resp_target.upper() == which.nickname.upper():
                target = resp.origin.split('!')[0]

            else:
                target = resp_target

            await self.read(which, target, resp.params.data, resp)

            # Hey, let's also learn from messages! They must start with either an
            # alphanumeric character, whitespace, or a dash, for security
            # reasons.

            line = resp.params.data

            if re.match(r'[a-zA-Z0-9\s\-]', line[0]):
                self.snobe.brain.learn(line)

            # Also, let's detect for nickname triggers.

            if which.nickname in line.split(' '):
                respond_to = line.strip()

                await which.message(target, self.snobe.brain.reply(respond_to, loop_ms=300)[:200].replace('\n', ' '))

    def init(self):
        """Initializes this bot.
        """

        @self.add_command('ping', 'Pong?')
        # pylint: disable=unused-variable
        def define_ping(define, reply):
            @define
            # pylint: disable=unused-variable
            async def ping(_, *args):
                await reply('Ye pong to "{}", yohohoh\'!'.format(' '.join(args)))

        reddit = self.snobe.reddit

        @self.add_command('ask', 'Asks the COBE chatbot a query.')
        # pylint: disable=unused-variable
        def define_ask(define, reply, loop_ms=300):
            @define
            async def ask(_, *message):
                msg = ' '.join(message).strip() or None

                await reply(self.snobe.brain.reply(msg, loop_ms=loop_ms)[:200].replace('\n', ' '))

        @self.add_command('learnsub', 'Tells the COBE chatbot to learn from some Subreddit.')
        # pylint: disable=unused-variable
        def define_sub_learn(define, reply):
            @define
            async def learn_from(_, subreddit, limit='30'):
                subreddit = reddit.subreddit(subreddit)

                if subreddit:
                    for subm in subreddit.hot(limit=int(limit)):
                        if hasattr(subm, 'body'):
                            self.snobe.learn(subm)

                    await reply("Learned successfully.")

                else:
                    await reply("Error: no such subreddit!")

        @self.add_command('learnpost', 'Tells the COBE chatbot to learn from a single submission.')
        # pylint: disable=unused-variable
        def define_learn(define, reply):
            @define
            async def learn_post(_, arg):
                subm = reddit.submission(arg)

                if hasattr(subm, 'body'):
                    self.snobe.check_learn(subm)
                    await reply("Learned successfully.")

                else:
                    await reply("Error: no such submission!")

        @self.add_command('learncom', 'Tells the COBE chatbot to learn from a single comment.')
        # pylint: disable=unused-variable
        def define_learn_one(define, reply):
            @define
            async def learn_one(_, arg):
                comm = reddit.comment(arg)

                if hasattr(comm, 'body'):
                    self.snobe.learn(comm)
                    await reply("Learned successfully.")

                else:
                    await reply("Error: no such comment!")

        for backend in self.backends:
            # Log sent lines.
            @backend.listen('_SENT')
            # pylint: disable=unused-variable
            async def on_sent_line(_, line):
                print('>>> ' + line)

            # Log received lines.
            @backend.listen('_RAW')
            # pylint: disable=unused-variable
            async def on_raw(_, line):
                print('<<< ' + line)



if __name__ == '__main__':
    BOT = Grit(
        host='irc.freenode.net',
        port=6667,
        nickname='GritBot',
        channels=set(x.strip() for x in open("channels.txt").read().strip().split('\n'))
    )
    BOT.register_mutator(AntiHilite())
    trio_asyncio.run(BOT.start)
