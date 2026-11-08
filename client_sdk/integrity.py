"""
devil.integrity — signed-manifest integrity check for a game's OWN files.

This is the legitimate version of "if it's been tampered with, don't let the
game open." It checks the GAME'S files (and the anti-cheat's own user-mode
files) against a manifest the company SIGNS with an Ed25519 private key. The
client ships only the PUBLIC key, so a cheater can't forge a manifest, and a
patched game binary (a classic cheat vector) is caught at launch.

How it differs from the kernel-driver self-heal you asked about:
  - It verifies ordinary files on disk, not a hidden kernel component.
  - On failure it REFUSES TO LAUNCH and tells the player what to do. Any
    repair re-downloads the game's own files WITH the player's consent — it
    does not silently reinstall system-level components or resist removal.
  - No kernel, no persistence, no fighting the user for control of their PC.

Requires `cryptography` (Ed25519).
"""

from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)
from cryptography.hazmat.primitives import serialization


# ---- key helpers (the company runs keygen once; keeps the private key safe) --
def generate_keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_bytes = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())
    pub_bytes = pub.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return priv_bytes.hex(), pub_bytes.hex()


def _hash_file(path, chunk=65536):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# ---- build + sign (company side, at release time) --------------------------
def build_manifest(root: str, rel_files: list[str], version: str) -> dict:
    entries = {}
    for rel in rel_files:
        p = os.path.join(root, rel)
        entries[rel] = _hash_file(p)
    return {"version": version, "files": entries}


def sign_manifest(manifest: dict, priv_hex: str) -> dict:
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    sig = priv.sign(body)
    return {"manifest": manifest, "sig": sig.hex()}


# ---- verify (client side, every launch) ------------------------------------
@dataclass
class IntegrityResult:
    ok: bool
    signature_valid: bool
    missing: list = field(default_factory=list)
    modified: list = field(default_factory=list)
    message: str = ""


def verify(root: str, signed: dict, pub_hex: str) -> IntegrityResult:
    pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
    body = json.dumps(signed["manifest"], sort_keys=True,
                      separators=(",", ":")).encode()
    try:
        pub.verify(bytes.fromhex(signed["sig"]), body)
        sig_ok = True
    except Exception:
        return IntegrityResult(False, False,
                               message="manifest signature INVALID — refusing "
                                       "to trust it")
    missing, modified = [], []
    for rel, want in signed["manifest"]["files"].items():
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            missing.append(rel)
        elif _hash_file(p) != want:
            modified.append(rel)
    ok = not missing and not modified
    if ok:
        msg = "all files verified"
    else:
        msg = (f"integrity check FAILED: {len(missing)} missing, "
               f"{len(modified)} modified")
    return IntegrityResult(ok, sig_ok, missing, modified, msg)
