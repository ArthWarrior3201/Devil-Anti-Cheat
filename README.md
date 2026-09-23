# Devil Anti-Cheat 0.3

An anti-cheat-only edition: **no player licenses, activation keys, purchase checks,
store ownership, subscriptions, or hardware activation limits.** This separate
edition is named Devil Anti-Cheat throughout its package and commands.

It provides signed game-file checks plus a working reference game server that
controls gameplay rules. It is not yet installed into your particular game,
because its source and networking interface have not been supplied in this task.
The included arena is a test integration, not a complete game or universal EXE plugin.

## Run the demonstration

Requires Python 3.10 or newer. Extract the ZIP and open a terminal inside
`Devil-Anti-Cheat`:

```bat
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m devil_anticheat demo
```

The demo detects a modified temporary game file, rejects requests with invented
speed/damage/health/coin values, accepts a normal action, and rejects a rapid
repeat during cooldown. It does not modify existing games or system settings.

On macOS/Linux use `python3 -m venv .venv`, then `.venv/bin/python` instead of
`.venv\Scripts\python`. Verification was run on Linux/Python 3.12 with
cryptography 46.0.0. The Windows commands have not been run on a Windows machine.

## Included checks

| Attempt | Implemented response |
| --- | --- |
| Edit code or data in the checked release folder | SHA-256 inventory identifies changed files |
| Remove or add files | Exact signed inventory identifies missing/unexpected files |
| Edit the release manifest | Ed25519 signature verification fails with the original trusted public key |
| Send a higher movement speed, new position, or fake elapsed time | Reject unknown fields; server computes motion from direction and its own ticks |
| Move faster diagonally | Normalize the direction vector |
| Send commands faster to gain distance | Simulation time is independent of command count; command budget also limits flooding |
| Walk through the example wall | Server collision test stops movement |
| Request excessive damage | No client damage parameter is accepted; server applies its damage constant |
| Attack too rapidly, too far away, or through the wall | Server cooldown, range and line-of-sight checks reject it |
| Use infinite ammo or instant reload | Ammo and reload completion live in server state |
| Set health or grant coins | Those commands do not exist; health/rewards come from server rules |
| Collect the same coin repeatedly | Server removes the collectible when it awards the reward |
| Replay an action packet | Session-specific increasing sequence number rejects it |

Invalid actions are refused; they are not automatically treated as proof of
cheating or grounds for a permanent ban. Diagnostics remain in a bounded in-memory
event list. No unrelated programs or files are scanned. No saves are deleted.

## Why server control matters

A changed client can draw any local health number or replace a local checker.
It cannot change the trusted server's health value merely by submitting that
number. Other clients should display and act on the server's state.

This requires a server controlled by the developer or a trusted operator. Running
the authoritative server on the same machine controlled by the person modifying
the game does not establish that protection. The included localhost server lets
you test the design, not prove your own machine is tamper-free.

For a fully offline game, file checks can detect changes when the checker is
intact, but cannot guarantee that a determined user cannot patch the checker or
modify memory. This edition does not claim to stop every cheat, wallhack, aimbot,
automation tool, or injected code.

## Integrate file checking

Keep the code/assets you want to verify in a dedicated immutable folder, such as
`game-code`. Put saves, logs, screenshots, caches and generated files outside it.
For Python code, disable bytecode writing or put its cache outside the checked
folder; newly generated `__pycache__` files otherwise appear as unexpected files.

Create developer signing keys once:

```bat
.venv\Scripts\python -m devil_anticheat keys developer-keys
```

Sign an inventory for a release:

```bat
.venv\Scripts\python -m devil_anticheat seal game-code --private-key developer-keys\developer-private.json --output release-manifest.json --build 1
```

The keys identify the official build. **They are developer signing keys, not
player license keys.** Keep the private key on your build/developer machine.
Ship the manifest and trusted public key with your game. A new legitimate release
needs a new signed inventory.

Check the release:

```bat
.venv\Scripts\python -m devil_anticheat check game-code --manifest release-manifest.json --public-key developer-keys\developer-public.json
```

In an app/launcher:

```python
from devil_anticheat import FileGuard, IntegrityError

guard = FileGuard(
    root="game-code",
    manifest_path="release-manifest.json",
    public_key="YOUR_BUILD_PUBLIC_KEY_BASE64",
)
try:
    guard.require_clean()
except IntegrityError:
    # Present a repair/retry message instead of entering a protected match.
    raise
```

Call this before loading the checked files, and at appropriate boundaries if
desired. Hashing a whole large installation every frame would be expensive.
Files are hashed in streaming chunks and the reference inventory supports up to
10,000 files and a 2 MiB manifest. Symlinks in the checked folder are refused.

This is a point-in-time disk check, not a memory scanner. Files can change after
the check. A client report saying "clean" is not proof to a server, and this
implementation intentionally does not pretend it is remote attestation. Someone
who can patch the verifier and replace its trusted public key can bypass it.

## Integrate authoritative actions

The Python `Arena` class demonstrates the separation needed for your actual game:

1. Your game sends input/intention, such as a direction or an attack request.
2. The trusted server validates the request against its own world state.
3. The server changes position, health, ammo, cooldowns or rewards.
4. Clients use the resulting state for gameplay. Local prediction must reconcile
   with the authoritative result, rather than override it.

For the reference protocol:

```python
from devil_anticheat import MatchClient, ActionRejected

client = MatchClient("https://your-match-server.example")
client.join("Player")

try:
    state = client.command("move", dx=1, dy=0)
    # Render authoritative state; do not calculate final damage from client input.
except ActionRejected as error:
    print(error)
```

Allowed command schemas:

| Command | Arguments |
| --- | --- |
| `move` | `{"dx": number, "dy": number}` with each axis in [-1, 1] |
| `attack` | `{"target": "PLAYER_ID"}` |
| `reload` | `{}` |

The match server simulates at 20 ticks per second. Movement inputs expire after
five ticks without refresh (250 ms), so an integration should resend the current
direction about every 100 ms while moving. Large server stalls drop simulation
backlog to avoid granting a sudden movement jump; gameplay slows during such a
stall. This demo has no client prediction, latency compensation, jumping, physics
engine integration or respawn system. Adapt those rules on the server for your game.

`Arena.SPEED`, `DAMAGE`, `RANGE`, `COOLDOWN` and `RELOAD` are developer/server rules.
Changing client copies of these constants has no authority over a separately
hosted server. Add only the actions your own game actually supports. For example,
a game without flight should never accept a client-provided flying position.

SDK methods are synchronous. Use a worker thread or your engine's networking
system so requests do not block the frame loop. One `MatchClient` instance should
be owned by one thread. After losing a response, `state()` resynchronizes sequence
numbers. Do not automatically replay actions with external side effects.

## Try two local clients

Terminal 1:

```bat
.venv\Scripts\python -m devil_anticheat serve
```

Terminals 2 and 3:

```bat
.venv\Scripts\python -m devil_anticheat client --dev-http --name PlayerOne
```

Use a different name in the second client. Commands: `state`, `move 1 0`,
`attack PLAYER_ID`, `reload`, `quit`. The console is an integration test interface,
not a graphical game. Each manually entered move lasts at most 250 ms.

The development server binds only to `127.0.0.1:8766`. The client requires HTTPS
for non-loopback URLs and refuses redirects. Its random session token associates
commands with a player during a match; it is not a license or purchase check.
Do not share session tokens. TLS is required to protect them in a deployment.

## Deployment boundaries

This is a reference SDK and local server, not an Internet-hardened anti-cheat
service. It has basic per-session command budgets, a bounded join history, a
16-player cap and idle session expiry, but not full abuse prevention. Anonymous
joining is deliberately allowed in this sample. Connect your existing game login
or match authentication if needed; preventing extra accounts or abusive rejoins
requires additional game/session policies, not purchase licensing.

The example sends all player positions in snapshots and therefore does not
prevent an altered client revealing hidden players. A real game must decide which
information each player is allowed to receive. Likewise, choosing targets directly
does not detect aim assistance. The toy collision/map rules need replacement by
your actual authoritative physics and visibility rules.

No existing game files, C++/Java engine integration, native memory checks, TPM
binding, kernel driver, process scanner, stealth component, automatic ban system,
or universal executable wrapping is included. The Python SDK can be integrated
directly into Python games; other languages need an adapter to these rules and
protocols or equivalent server logic.

## Tests

```bat
.venv\Scripts\python -m unittest discover -s tests -v
```

The 31 tests cover valid and invalid movement, diagonal speed, packet-frequency
independence, stopped input, server stalls, collision, fixed damage, cooldowns,
range, wall occlusion, reload/ammo, health and rewards, replay, session handling,
rate limits, modified/missing/added files, forged manifests, and real HTTP traffic.
These tests establish the listed behaviours, not immunity to all cheating.
