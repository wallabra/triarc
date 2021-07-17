"""
The Command Reactor interface as used by bots.
"""

import typing
import attr

if typing.TYPE_CHECKING:
    from collections.abc import Iterable
    from .backend import Backend
    from .bot import Bot
    from .comms.wrapper import Message
    from .comms.base import ResponseDescriptor
    from typing import Union, Optional, Literal


@attr.s(autoattrib=True)
class RegisteredCommand:
    """A Command as registered in a Bot.

    This is what is created when a CommandReactor registers a
    command into a bot, whether locally or remotely.

    It is passed as a callback to the dedcorator function returned
    by CommandBot.add_command."""

    # The remote reactor interface.
    reactor: "RemoteCommandReactor"

    # The identifier of the command on the *reactor* side.
    command_id: str

    # The identifier of the command on the *bot* side.
    command_name: str

    # The command's help string.
    help_string: Optional[str]

    async def __call__(self, which: Backend, message: Message, *args: Iterable[str]):
        """Calls the command on the reactor."""
        self.reactor.call_command(self, self.command_id, message, which, *args)

    def register(self, bot: Bot):
        """Adds this RegisteredComanad to a Bot as a callback."""
        deco = bot.add_command(self.command_name, help_string=self.help_string)
        deco(self)


class CommandResult(typing.Protocol):
    """A result of a remote command."""

    def get_response(self) -> Optional[ResponseDescriptor]:
        """
        Returns a response to be given to the command issuer, if any.
        """
        ...

    def get_error(self) -> Optional[tuple[str, str, Iterable[str]]]:
        """
        Returns any error produced in the execution of a command, or None.

        This error is not raised; at most, it is replied (privately) to
        the command issuer.

        If the return value is not None, this indicates that an error was
        produced. It is sent, often in bold, in a plaintext format with the
        error's type name and message, which are the first and second items
        of the returned tuple, respectively. The third item of the tuple is
        a list of strings to be printed to the logger, generally a traceback.
        """
        ...


class RemoteCommandReactor(typing.Protocol):
    """
    An interface for a command reactor from a Bot's perspective, whether locally
    or remotely.
    """

    async def command_exists(self, command_id: str) -> bool:
        """Returns whether a command exists by ID."""
        ...

    async def list_commands(self) -> typing.AsyncGenerator[str, None, None]:
        """Yields a list of command IDs available."""
        ...

    async def call_command(
        self, command_id: str, which: Backend, message: Message, args: Iterable[str]
    ) -> Optional[trio.abc.ReceiveChannel[Union[CommandResult, Literal["finished"]]]]:
        """
        Calls a command callback remotely, returning None if the command does not
        exist, or otherwise an asynchronous queue of command results.
        """
        ...
