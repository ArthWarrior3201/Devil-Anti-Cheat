# Devil Anti-Cheat

A server-authoritative anti-cheat SDK for video games. The server owns the
game simulation; the client reports intent and integrity signals. Enforcement is
reversible and leaves nothing behind on the player's machine.

## Features

- Server-side validation of movement, aim, hits, and visibility
- Hardware-hash blacklisting (reversible, enforced on your server)
- Ed25519 signed-manifest file-integrity verification
- Virtual-machine detection as a scored signal
- Configurable blacklist client for your own backend
- Drop-in launch gate (`DevilClient`)

## Repository layout

```
devil-anti-cheat/
├── client_sdk/                 # Client SDK that ships with your game
│   ├── devil_client.py         #   DevilClient.verify_launch() — entry point
│   ├── fingerprint.py          #   hardware-hash collection
│   ├── integrity.py            #   Ed25519 signed-manifest verify
│   ├── vmsignal.py             #   VM detection (scored signal)
│   └── blacklist_client.py     #   client for your ban server
├── server_core_interface/      # Server-side contracts to implement
├── index.html                  # Project landing page (GitHub Pages)
├── assets/                     # Landing-page assets
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

`verify_launch` runs, in order: file integrity → VM policy (optional,
configurable) → hardware blacklist. The ban decision is a server read, so an
approved appeal lifts it with one write.

## Configuration

Copy `devil_protocol.sample.json` to `devil_protocol.json` and set your
endpoint, auth, field mapping, timeouts, and fail mode. The SDK reads it at
startup.

## Server side

Implement the contracts in `server_core_interface/` on your backend — the
authoritative simulation, detection scoring, and ban store. The SDK talks to
them over your configured protocol.

## Landing page

`index.html` is a self-contained page served from the repository root via
GitHub Pages (Settings → Pages → deploy from the default branch, root folder).

## License

Add your license here.
