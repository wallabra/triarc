from triarc.bot import Bot



class Manager(object):
    def __init__(self):
        self.bots = set()

    def add_bot(self, bot: Bot):
        self.bots.add(bot)

    def start(self):
        for b in self.bots:
            b.start()