"""
Devil Anti-Cheat — Client SDK (public).

This package is what a game integrates. It is safe to publish: every line here
already runs on the player's machine, so hiding it would buy no security. The
parts that must stay secret (detection heuristics, scoring thresholds, the
authoritative simulation) are NOT here — they run on your private server. See
the repo README for the public/private split.
"""
__version__ = "0.2.0"

try:
    from .devil_client import DevilClient, LaunchPolicy
except ImportError:
    from devil_client import DevilClient, LaunchPolicy

__all__ = ["DevilClient", "LaunchPolicy"]
