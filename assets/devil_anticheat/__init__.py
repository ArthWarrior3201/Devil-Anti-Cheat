"""Devil Anti-Cheat: signed file checks and authoritative gameplay validation."""
from .arena import Arena, ActionRejected
from .integrity import FileGuard, IntegrityError
from .network import MatchClient, MatchServer

__version__ = "0.3.0"
__all__ = ["Arena", "ActionRejected", "FileGuard", "IntegrityError", "MatchClient", "MatchServer"]
