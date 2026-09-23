import argparse
from pathlib import Path
import tempfile
import threading
from . import Arena, ActionRejected, FileGuard, IntegrityError, MatchClient, MatchServer
from .integrity import create_keys, read_json, seal


def demo():
    print("Devil Anti-Cheat | no licenses, activation, or ownership checks")
    with tempfile.TemporaryDirectory(prefix="devil-anticheat-") as temp:
        root = Path(temp)
        game = root / "game-code"
        game.mkdir()
        (game / "rules.txt").write_text("normal game build", encoding="utf-8")
        create_keys(root / "developer")
        seal(game, root / "developer/developer-private.json", root / "manifest.json")
        guard = FileGuard(game, root / "manifest.json", read_json(root / "developer/developer-public.json")["public"])
        print("Original files:", guard.require_clean()["ok"])
        (game / "rules.txt").write_text("modified build", encoding="utf-8")
        print("Modified file detected:", guard.check()["changed"])
    with MatchServer(Arena(), 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            first, second = MatchClient(url, True), MatchClient(url, True)
            first.join("Player")
            second.join("Training partner")
            for action, arguments in (
                ("move", {"dx": 1, "dy": 0, "speed": 999}),
                ("attack", {"target": second.player_id, "damage": 9999}),
                ("set_health", {"hp": 9999}),
                ("grant_coins", {"coins": 9999})):
                try:
                    first.command(action, **arguments)
                    raise RuntimeError("Unexpected acceptance of an invalid command")
                except ActionRejected as exc:
                    print("Rejected:", exc)
            state = first.command("attack", target=second.player_id)
            partner = next(p for p in state["players"] if p["id"] == second.player_id)
            print("Valid action: partner HP =", partner["hp"], "(server applied normal 10 damage)")
            try:
                first.command("attack", target=second.player_id)
                raise RuntimeError("Cooldown check failed")
            except ActionRejected as exc:
                print("Rapid repeat rejected:", exc)
        finally:
            server.shutdown()
            thread.join(timeout=3)
    print("Demo completed. This is a reference integration, not installed into your game yet.")


def main():
    parser = argparse.ArgumentParser(description="Devil Anti-Cheat 0.3")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo")
    cmd = commands.add_parser("keys", help="Create developer signing keys, not player licenses")
    cmd.add_argument("folder")
    cmd = commands.add_parser("seal", help="Sign a release's game-code file inventory")
    cmd.add_argument("game_folder")
    cmd.add_argument("--private-key", required=True)
    cmd.add_argument("--output", required=True)
    cmd.add_argument("--build", default="1")
    cmd = commands.add_parser("check", help="Verify files against a signed release inventory")
    cmd.add_argument("game_folder")
    cmd.add_argument("--manifest", required=True)
    cmd.add_argument("--public-key", required=True)
    cmd = commands.add_parser("serve")
    cmd.add_argument("--port", type=int, default=8766)
    cmd = commands.add_parser("client", help="Interactive integration console")
    cmd.add_argument("--server", default="http://127.0.0.1:8766")
    cmd.add_argument("--dev-http", action="store_true")
    cmd.add_argument("--name", default="Player")
    args = parser.parse_args()
    try:
        if args.command == "demo": demo()
        elif args.command == "keys":
            create_keys(args.folder)
            print("Developer signing keys created. Keep the private key out of the game distribution.")
        elif args.command == "seal":
            seal(args.game_folder, args.private_key, args.output, args.build)
            print("Signed release manifest created.")
        elif args.command == "check":
            guard = FileGuard(args.game_folder, args.manifest, read_json(args.public_key)["public"])
            result = guard.check()
            print(result)
            return 0 if result["ok"] else 1
        elif args.command == "serve":
            with MatchServer(Arena(), args.port) as server:
                print(f"Devil Anti-Cheat development server: http://127.0.0.1:{server.server_port}", flush=True)
                server.serve_forever()
        elif args.command == "client":
            client = MatchClient(args.server, args.dev_http)
            client.join(args.name)
            print("Player ID:", client.player_id)
            print("Commands: state | move DX DY | attack PLAYER_ID | reload | quit")
            while True:
                words = input("> ").split()
                if not words: continue
                try:
                    if words == ["quit"]: break
                    if words == ["state"]: print(client.state())
                    elif len(words) == 3 and words[0] == "move":
                        print(client.command("move", dx=float(words[1]), dy=float(words[2])))
                    elif len(words) == 2 and words[0] == "attack":
                        print(client.command("attack", target=words[1]))
                    elif words == ["reload"]: print(client.command("reload"))
                    else: print("Unknown command")
                except (ActionRejected, ValueError) as exc:
                    print("Action refused:", exc)
        return 0
    except (KeyboardInterrupt, EOFError):
        print("Stopped normally.")
        return 0
    except (ActionRejected, IntegrityError, OSError, ValueError, KeyError) as exc:
        print("Unable to continue:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
