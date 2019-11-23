"""
A mutator preset that prevents messages that highlight
anyone in a given target. Currently works on IRC only.
"""

import re

from triarc.mutator import Mutator
from triarc.backends.irc import IRCResponse
from triarc.backend import Backend
from triarc.bot import Bot



class AntiHilite(Mutator):
    """
    A mutator that cancels messages known to highlight anyone
    in a channel.
    """

    def __init__(self):
        self.nick_sets = {}

    # pylint: disable=unused-argument
    async def on_join(self, bot: Bot, which: Backend, event: IRCResponse):
        """Ran when someone joins. And I mean it."""

        if '!' in event.origin and event.params.args[0] in '#+!':
            # Register this nick.
            self.nick_sets.setdefault(
                (which, event.params.args[0]), set()
            ).add(event.origin.split('!')[0])

    # pylint: disable=unused-argument
    async def on_part(self, bot: Bot, which: Backend, event: IRCResponse):
        """Ran when someone leaves. And I really mean it."""

        if '!' in event.origin and event.params.args[0] in '#+!':
            # Unregister this nick.
            nick_set = self.nick_sets.setdefault(
                (which, event.params.args[0]), set()
            )
            nick = event.origin.split('!')[0]

            if nick in nick_set:
                nick_set.remove(nick)

    def registered(self, bot: Bot):
        """Ran when this mutator is registered."""

        @bot.any_listener
        # pylint: disable=unused-variable
        # pylint: disable=unused-argument
        async def check_names(bot: Bot, backend: Backend, kind: str, event: IRCResponse):
            """
            Check server responses for names lists (numerics), and parse
            and register nicks.
            """

            if kind == '_NUMERIC' and event.is_numeric and event.kind == '353':
                # NAMES list detected, parse and register nicks
                channel = event.params.args[-1]
                nicks = event.params.data.split(' ')

                for nick in nicks:
                    nick = nick.lstrip('@+&%*')

                    self.nick_sets.setdefault(
                        (backend, channel), set()
                    ).add(nick)

    def modify_message(self, backend: Backend, target: str, message: str) -> str:
        nicks = self.nick_sets.get((backend, target), set())

        for nick in nicks:
            if nick in re.split(r'[^a-zA-Z0-9\-\[\]\_]+', message) and nick != backend.nickname:
                return None

        # Anti-highlight test passed, message greenlit.
        return message
