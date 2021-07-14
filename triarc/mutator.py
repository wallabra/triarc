"""
Mutators are extensions that can modify the behavior of Triarc bots.
"""

import triarc


class Mutator:
    """
    The base Mutator superclass. Supposed to be subclassed.

    Mutators are used by the Bot class in order to modify
    or interface with their behavior, being essentially
    extensions.
    """

    async def on_any(self, backend: "triarc.backend.Backend", kind: str, data: any):
        """
        This method is called by the Bot whenever any backend
        event is emitted.

        Arguments:
            backend {triarc.backend.Backend} -- The backend that caused this event.

            kind {str} -- The kind of backend event.
            data {any} -- The data of this backend event.
        """
        pass

    def modify_message(
        self, backend: "triarc.backend.Backend", target: any, message: str
    ) -> str:
        """
        Modifies any message sent to a backend target by the Bot.
        Returns the modified version of this message.

        Arguments:
            backend {triarc.backend.Backend} -- The backend whose outgoing message to be modified.

            target {any} -- The target. This is actually any object that can be
                            accepted in backend.message, so always use repr()!

            message {str} -- The message.
        """
        return message
