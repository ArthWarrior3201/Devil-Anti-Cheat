"""
server_core_interface — the PRIVATE half, published as interfaces ONLY.

These are the signatures a Devil server implements. The real implementations
(the authoritative movement/aim simulation, the detection scoring weights and
thresholds, the ban storage) are intentionally NOT in this public repo: they
run on your server, and exposing their internals would let cheaters tune
evasion against your exact thresholds.

This file exists so integrators understand the shape of the server side. It is
not a working implementation and deliberately contains no heuristics, weights,
thresholds, or detection logic. Every method raises NotImplementedError.
"""

from __future__ import annotations
from abc import ABC, abstractmethod


class AuthorityCore(ABC):
    """Server-authoritative simulation. The server owns truth; clients send
    intent only. (Implementation private — runs on your match servers.)"""

    @abstractmethod
    def apply_move_intent(self, player_id: int, intent: dict) -> None:
        """Validate and apply a movement INTENT. Never trust client position."""
        raise NotImplementedError

    @abstractmethod
    def apply_fire_intent(self, player_id: int, intent: dict) -> dict:
        """Resolve a shot against server state (aim, range, LOS, cooldown)."""
        raise NotImplementedError

    @abstractmethod
    def snapshot_for(self, viewer_id: int) -> dict:
        """Return ONLY what this viewer may perceive (anti-wallhack)."""
        raise NotImplementedError


class DetectionBackend(ABC):
    """Scores signals into reviewable evidence. (Weights/thresholds private.)"""

    @abstractmethod
    def ingest_violation(self, account_id: str, violation: dict) -> None:
        raise NotImplementedError

    @abstractmethod
    def ingest_vm_signal(self, account_id: str, report: dict) -> None:
        raise NotImplementedError

    @abstractmethod
    def open_reviews(self) -> list:
        """Accounts whose evidence crossed the review threshold."""
        raise NotImplementedError


class BlacklistStore(ABC):
    """Hardware-hash ban storage behind your HTTPS endpoint. Reversible."""

    @abstractmethod
    def check(self, hwid_hash: str) -> tuple[bool, str]:
        raise NotImplementedError

    @abstractmethod
    def ban(self, hwid_hash: str, reason: str, evidence: list) -> None:
        raise NotImplementedError

    @abstractmethod
    def approve_appeal(self, hwid_hash: str) -> bool:
        """Lift a ban — one server write. Nothing touches the player's PC."""
        raise NotImplementedError
