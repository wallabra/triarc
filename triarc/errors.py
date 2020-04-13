class TriarcError(Exception):
    """
    A common superclass for all
    exceptions regarding Triarc.
    """
    pass

# == Backend errors ==

class TriarcBackendError(TriarcError):
    """
    A common superclass for all exceptions
    involving triarc.backend.Backend and
    subclasses thereof.
    """
    pass

# == Bot errors ==

class TriarcBotError(TriarcError):
    """
    A common superclass for all exceptions
    involving triarc.bot.Bot and subclasses
    thereof.
    """
    pass

class TriarcBotBackendRefusedError(TriarcBotError):
    """
    Raised when a backend refuses to be registered
    by a Bot, when such register operation is
    called with `required=True`.
    """
    pass
