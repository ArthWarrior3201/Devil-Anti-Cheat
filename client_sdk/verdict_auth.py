"""
devil.verdict_auth — authenticate the server's ban verdict.

The problem it solves: a cheat can point the client at a fake local "server"
that just answers "not banned". To stop that, the REAL server signs every
verdict with an Ed25519 private key (kept off the player's machine). The client
verifies the signature with the server's PUBLIC key, embedded in the game.

A fake server can't forge a valid signature without the private key, so the
client can tell a real verdict from a fake one. The signature covers a
per-request nonce, so a captured "not banned" response can't be replayed.

(Honest limit: if the attacker patches the CLIENT binary to skip verification
or swaps the embedded public key, they still win — that's the fundamental
"attacker owns the machine" ceiling. Signing raises the bar from "trivial"
to "must patch and re-ship the client", and the authoritative simulation
still runs server-side where patching does nothing.)

Shared helper: the server imports `sign_verdict`; the client uses
`verify_verdict`.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)


def _canonical(nonce: str, banned: bool, reason: str) -> bytes:
    # Fixed, unambiguous encoding so client and server sign/verify the same bytes.
    return f"{nonce}|{1 if banned else 0}|{reason}".encode("utf-8")


def sign_verdict(nonce: str, banned: bool, reason: str, priv_hex: str) -> str:
    """Server side: sign a verdict for a given request nonce."""
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
    return priv.sign(_canonical(nonce, banned, reason)).hex()


def verify_verdict(nonce: str, banned: bool, reason: str,
                   sig_hex: str, pub_hex: str) -> bool:
    """Client side: is this verdict genuinely from the holder of the key?"""
    if not sig_hex or not pub_hex:
        return False
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
        pub.verify(bytes.fromhex(sig_hex), _canonical(nonce, banned, reason))
        return True
    except Exception:
        return False
