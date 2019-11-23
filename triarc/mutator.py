"""
Mutators are extensions that can modify the behavior of Triarc bots.
"""

from triarc.backend import Backend



class Mutator:
    """
    The base Mutator superclass. Supposed to be subclassed.

    Mutators are used by the Bot class in order to modify
    or interface with their behavior, being essentially
    extensions.
    """

    async def on_any(self, backend: Backend, kind: str, data: any):
        """
        This method is called by the Bot whenever any backend
        event is emitted.
        """

    def modify_message(self, backend: Backend, target: str, message: str) -> str:
        """
        Modifies any message sent to a backend target by the Bot.
        Returns the modified version of this message.
        """
        return message
