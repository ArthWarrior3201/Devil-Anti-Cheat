"""
devil_client — the single entry point a game calls at launch.

    from client_sdk import DevilClient, LaunchPolicy

    client = DevilClient(
        public_key_hex=MY_EMBEDDED_PUBLIC_KEY,
        protocol_config_path="devil_protocol.json",   # optional
    )
    decision = client.verify_launch(game_root=".", signed_manifest=manifest)
    if not decision["allow"]:
        show(decision["message"])        # e.g. "SORRY, YOU ARE BANNED"
        sys.exit(1)

What this does, in order:
    1. Integrity  — verify the game's own files against the signed manifest.
    2. VM policy  — optionally refuse to launch in a virtual machine.
    3. Blacklist  — ask your server whether this hardware hash is banned.

Every decision that matters (the ban) is a server read, so it's reversible.
Nothing is written to, hidden on, or removed from the player's machine.
"""

from __future__ import annotations
from dataclasses import dataclass

try:
    from . import fingerprint, vmsignal, integrity
    from .blacklist_client import load_config, BlacklistClient
except ImportError:
    import fingerprint, vmsignal, integrity
    from blacklist_client import load_config, BlacklistClient


@dataclass
class LaunchPolicy:
    deployment_salt: str = "company-deployment-salt"
    block_vms: bool = True
    vm_block_threshold: float = 0.5
    require_integrity: bool = True


class DevilClient:
    def __init__(self, public_key_hex: str,
                 protocol_config_path: str | None = None,
                 blacklist_transport=None):
        self.public_key_hex = public_key_hex
        self.cfg = load_config(protocol_config_path)
        self.blacklist = BlacklistClient(self.cfg, transport=blacklist_transport)

    def hardware_hash(self, policy: LaunchPolicy) -> str:
        fp = fingerprint.collect()
        # The ban scope IS the hash salt, so the same machine hashes differently
        # per scope and a ban can't leak across unrelated games/brands.
        salt = self.cfg.get("scope") or policy.deployment_salt
        return fingerprint.fingerprint_hash(fp["components"], salt)

    def verify_launch(self, game_root: str, signed_manifest: dict,
                      policy: LaunchPolicy | None = None) -> dict:
        policy = policy or LaunchPolicy()

        # 1. integrity of the game's own files
        if policy.require_integrity and signed_manifest is not None:
            r = integrity.verify(game_root, signed_manifest, self.public_key_hex)
            if not r.ok:
                return {"allow": False, "code": "INTEGRITY",
                        "message": "Game files are missing or modified. "
                                   "Please verify or reinstall.",
                        "detail": {"missing": r.missing, "modified": r.modified,
                                   "signature_valid": r.signature_valid}}

        # 2. VM policy (company-configurable; spoofable signal, so optional)
        vm = vmsignal.collect().as_report()
        if policy.block_vms and vm["confidence"] >= policy.vm_block_threshold:
            return {"allow": False, "code": "VM_BLOCKED",
                    "message": "This game can't be launched in a virtual machine.",
                    "detail": {"vm_confidence": vm["confidence"]}}

        # 3. hardware blacklist (the ban lives on your server)
        hwid = self.hardware_hash(policy)
        res = self.blacklist.check(hwid)
        if res.banned:
            return {"allow": False, "code": "BANNED",
                    "message": "SORRY, YOU ARE BANNED",
                    "detail": {"reason": res.reason, "hwid": hwid}}

        # If signed verdicts are required, an UNTRUSTED "not banned" (a fake
        # local server, a tampered or unsigned reply) must not pass. This is
        # what stops a cheat from pointing the client at a server that just
        # says "ok". A genuinely unreachable real server lands here too — when
        # you require signing you are choosing fail-closed on trust.
        if self.cfg.get("require_signed_response") and not res.trusted:
            return {"allow": False, "code": "UNVERIFIED",
                    "message": "Couldn't verify your status with the server. "
                               "Check your connection and try again.",
                    "detail": {"hwid": hwid, "server_reachable": res.ok,
                               "note": res.note}}

        return {"allow": True, "code": "OK", "message": "Launch allowed.",
                "detail": {"hwid": hwid, "server_reachable": res.ok,
                           "trusted": res.trusted}}
