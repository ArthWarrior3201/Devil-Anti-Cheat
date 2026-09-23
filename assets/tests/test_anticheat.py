import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
from devil_anticheat import Arena, ActionRejected, FileGuard, IntegrityError, MatchClient, MatchServer
from devil_anticheat.integrity import create_keys, seal, read_json


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def step(self, seconds): self.now += seconds


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.arena = Arena(self.clock)
        self.one = self.arena.join("One")
        self.two = self.arena.join("Two")
        self.a = self.arena.players[self.one["player_id"]]
        self.b = self.arena.players[self.two["player_id"]]
        self.seq = 0

    def command(self, action, **args):
        self.seq += 1
        return self.arena.command(self.one["session"], self.seq, action, args)

    def step(self, ticks=1):
        for _ in range(ticks):
            self.clock.step(0.05)
            self.arena.advance()

    def test_normal_movement(self):
        self.command("move", dx=1, dy=0)
        self.step(4)
        self.assertAlmostEqual(self.a.x, 3.0)

    def test_diagonal_not_faster(self):
        self.command("move", dx=1, dy=1)
        self.step(4)
        self.assertAlmostEqual(math.hypot(self.a.x - 2, self.a.y - 2), 1.0)

    def test_speed_and_position_fields_rejected(self):
        for extra in ({"speed": 999}, {"x": 19}, {"dt": 999}, {"timestamp": 999}):
            with self.assertRaises(ActionRejected): self.command("move", dx=1, dy=0, **extra)
        self.assertEqual(self.a.x, 2)

    def test_bad_numeric_inputs(self):
        for value in (1000, float("nan"), float("inf"), True, "1", 10**500):
            with self.assertRaises(ActionRejected): self.command("move", dx=value, dy=0)

    def test_more_packets_do_not_create_more_time(self):
        for _ in range(20): self.command("move", dx=1, dy=0)
        self.assertEqual(self.a.x, 2)
        self.step()
        self.assertEqual(self.a.x, 2.25)

    def test_input_stops_without_refresh(self):
        self.command("move", dx=1, dy=0)
        self.step(20)
        self.assertEqual(self.a.x, 3.25)

    def test_server_stall_does_not_teleport(self):
        self.command("move", dx=1, dy=0)
        self.clock.step(100)
        self.arena.advance()
        self.assertLessEqual(self.a.x - 2, 1.25)

    def test_wall_collision(self):
        self.a.x, self.a.y = 8.5, 10
        self.command("move", dx=1, dy=0)
        self.step(5)
        self.assertLess(self.a.x, 8.7)

    def test_fixed_damage(self):
        self.command("attack", target=self.b.id)
        self.assertEqual(self.b.hp, 90)
        self.assertEqual(self.a.ammo, 5)

    def test_extra_damage_cannot_be_submitted(self):
        with self.assertRaises(ActionRejected): self.command("attack", target=self.b.id, damage=10000)
        self.assertEqual(self.b.hp, 100)

    def test_fire_rate_enforced(self):
        self.command("attack", target=self.b.id)
        with self.assertRaises(ActionRejected): self.command("attack", target=self.b.id)
        self.step(10)
        self.command("attack", target=self.b.id)
        self.assertEqual(self.b.hp, 80)

    def test_range_enforced(self):
        self.b.x = 19
        with self.assertRaises(ActionRejected): self.command("attack", target=self.b.id)

    def test_no_attack_through_wall(self):
        self.a.x, self.a.y, self.b.x, self.b.y = 8.5, 10, 11.5, 10
        with self.assertRaises(ActionRejected): self.command("attack", target=self.b.id)
        self.assertEqual(self.b.hp, 100)

    def test_ammo_and_reload_delay(self):
        self.a.ammo = 0  # Server-side fixture, never client-supplied state.
        with self.assertRaises(ActionRejected): self.command("attack", target=self.b.id)
        self.command("reload")
        self.step(29)
        self.assertEqual(self.a.ammo, 0)
        self.step()
        self.assertEqual(self.a.ammo, 6)

    def test_cannot_attack_while_reloading(self):
        self.a.ammo = 1
        self.command("reload")
        with self.assertRaises(ActionRejected): self.command("attack", target=self.b.id)

    def test_no_client_health_or_coin_changes(self):
        for action, args in (("set_health", {"hp": 999}), ("grant_coins", {"coins": 999}),
                             ("set_ammo", {"ammo": 999})):
            with self.assertRaises(ActionRejected): self.command(action, **args)
        self.assertEqual((self.a.hp, self.a.coins, self.a.ammo), (100, 0, 6))

    def test_coin_awarded_once_from_server_position(self):
        self.command("move", dx=1, dy=0)
        self.step(4)
        self.assertEqual(self.a.coins, 10)
        self.command("move", dx=-1, dy=0)
        self.step(4)
        self.assertEqual(self.a.coins, 10)

    def test_dead_player_cannot_act(self):
        self.a.hp = 0
        with self.assertRaises(ActionRejected): self.command("move", dx=1, dy=0)

    def test_replay_rejected(self):
        self.command("attack", target=self.b.id)
        with self.assertRaises(ActionRejected):
            self.arena.command(self.one["session"], 1, "attack", {"target": self.b.id})
        self.assertEqual(self.b.hp, 90)

    def test_session_required_but_no_activation(self):
        with self.assertRaises(ActionRejected): self.arena.command("wrong", 1, "reload", {})
        self.assertTrue(self.arena.join("New player")["session"])

    def test_session_expiry(self):
        self.clock.step(121)
        with self.assertRaises(ActionRejected): self.arena.state(self.one["session"])

    def test_command_flood_limited(self):
        for _ in range(40): self.command("move", dx=0, dy=0)
        with self.assertRaises(ActionRejected): self.command("move", dx=0, dy=0)


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.game.mkdir()
        (self.game / "game.py").write_text("normal build")
        create_keys(self.root / "keys")
        self.manifest = self.root / "manifest.json"
        seal(self.game, self.root / "keys/developer-private.json", self.manifest)
        self.public = read_json(self.root / "keys/developer-public.json")["public"]

    def guard(self): return FileGuard(self.game, self.manifest, self.public)

    def test_clean_build(self): self.assertTrue(self.guard().require_clean()["ok"])

    def test_modified_code(self):
        (self.game / "game.py").write_text("modified build")
        self.assertEqual(self.guard().check()["changed"], ["game.py"])
        with self.assertRaises(IntegrityError): self.guard().require_clean()

    def test_missing_file(self):
        (self.game / "game.py").unlink()
        self.assertEqual(self.guard().check()["missing"], ["game.py"])

    def test_added_code(self):
        (self.game / "extra.py").write_text("extra code")
        self.assertEqual(self.guard().check()["unexpected"], ["extra.py"])

    def test_manifest_tampering(self):
        data = read_json(self.manifest)
        data["signature"] = "AAAA"
        self.manifest.write_text(json.dumps(data))
        with self.assertRaises(IntegrityError): self.guard()

    def test_wrong_publisher_key(self):
        create_keys(self.root / "other-keys")
        key = read_json(self.root / "other-keys/developer-public.json")["public"]
        with self.assertRaises(IntegrityError): FileGuard(self.game, self.manifest, key)

    def test_symlinks_rejected(self):
        (self.game / "alias").symlink_to(self.game / "game.py")
        with self.assertRaises(IntegrityError): self.guard().check()


class NetworkTests(unittest.TestCase):
    def test_real_http(self):
        with MatchServer(Arena(), 0) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                one, two = MatchClient(url, True), MatchClient(url, True)
                one.join("One")
                two.join("Two")
                with self.assertRaises(ActionRejected): one.command("move", dx=1, dy=0, speed=100)
                state = one.command("attack", target=two.player_id)
                self.assertEqual(next(p for p in state["players"] if p["id"] == two.player_id)["hp"], 90)
                self.assertNotIn("session", json.dumps(state))
                self.assertEqual(one.state()["next_sequence"], 3)
            finally:
                server.shutdown()
                thread.join(timeout=3)

    def test_remote_plain_http_rejected(self):
        with self.assertRaises(ValueError): MatchClient("http://example.com", True)
        with self.assertRaises(ValueError): MatchClient("http://127.0.0.1")


if __name__ == "__main__": unittest.main(verbosity=2)
