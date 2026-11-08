# Devil Anti-Cheat — v0.2

A server-authoritative anti-cheat SDK. The server owns the simulation; the
client only reports intent. Bans are reversible and nothing is hidden on or
written to the player's machine.

## This repo is the PUBLIC half, on purpose

Devil is split into a public client SDK and a private server core, for a
specific security reason:

- **Client code can't be protected by hiding it** — it already runs on the
  player's machine, so a cheater has it regardless. Publishing it costs you
  nothing, and open client code is easier to trust and audit.
- **The things worth keeping secret** — detection heuristics, scoring
  thresholds, the authoritative simulation — stay private by **running on your
  server**, not by obfuscation. Security through obscurity is not the plan;
  keeping the deciding logic off the client is.

So this repo ships the real client SDK and the *interfaces* of the server
core. It does **not** contain the server core's implementation (its heuristics,
weights, and thresholds). That's not a fake or stripped build to fool anyone —
it's the correct client/server boundary, stated honestly. You implement the
server core privately against `server_core_interface`.

```
devil-v0.2/
├── client_sdk/                 # PUBLIC — ships with your game
│   ├── devil_client.py         #   DevilClient.verify_launch() — the entry point
│   ├── fingerprint.py          #   user-mode hardware hash
│   ├── integrity.py            #   Ed25519 signed-manifest verify
│   ├── vmsignal.py             #   VM detection (scored signal)
│   └── blacklist_client.py     #   configurable client for your ban server
├── server_core_interface/      # PUBLIC — contracts only, no implementation
│   └── __init__.py             #   AuthorityCore / DetectionBackend / BlacklistStore
├── docs/
│   └── index.html              # GitHub Pages landing page
└── devil_protocol.sample.json  # copy to devil_protocol.json and edit
```

## Quick start

```python
from client_sdk import DevilClient, LaunchPolicy, integrity

# one time, on your build server — keep `priv` secret, embed `pub` in the game
priv, pub = integrity.generate_keypair()

# at release — sign the manifest of your shipped files
man = integrity.build_manifest(game_root, files, version="1.0.0")
signed = integrity.sign_manifest(man, priv)

# at launch — one call gates the game
client = DevilClient(public_key_hex=pub, protocol_config_path="devil_protocol.json")
d = client.verify_launch(game_root=".", signed_manifest=signed, policy=LaunchPolicy())
if not d["allow"]:
    show(d["message"]); raise SystemExit(1)
```

`verify_launch` runs, in order: game-file integrity → VM policy (optional,
configurable) → hardware blacklist (your server). The ban decision is a server
read, so an approved appeal lifts it with one write — reversible, no trace left
on the player's PC.

## What's deliberately NOT here

- **The server core implementation.** Private by design (see above).
- **A kernel driver.** v0.2 is user-mode only. A kernel anti-cheat driver needs
  an EV certificate, Microsoft attestation signing, and serious auditing — and
  the server-authoritative core already blocks the core gameplay cheats without
  one. Add a signed, audited kernel reader later only if the economics justify
  it.
- **Obfuscation/anti-decompile tricks.** "Undecompilable" is a myth; the only
  code a cheater genuinely can't crack is the code you never ship them — your
  server core.

## Publishing the landing page

`docs/index.html` is a self-contained GitHub Pages site. In your repo settings,
set Pages to serve from the `docs/` folder on your default branch.
