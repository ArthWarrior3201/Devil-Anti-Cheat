"""Authoritative reference rules. Clients send intentions, never final stats."""
from collections import deque
from dataclasses import dataclass
import math
import secrets
import threading
import time


class ActionRejected(Exception):
    pass


@dataclass
class Player:
    id: str
    name: str
    x: float
    y: float
    hp: int = 100
    ammo: int = 6
    coins: int = 0
    dx: float = 0
    dy: float = 0
    input_until: int = 0
    next_attack: int = 0
    reload_end: int = 0
    sequence: int = 0
    budget: float = 40
    budget_time: float = 0
    last_seen: float = 0


class Arena:
    TICK = 0.05
    SPEED = 5.0
    DAMAGE = 10
    RANGE = 4.0
    COOLDOWN = 10
    RELOAD = 30
    WALL = (9.0, 6.0, 11.0, 14.0)

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last_time = clock()
        self.tick = 0
        self.lock = threading.RLock()
        self.players = {}
        self.sessions = {}
        self.events = deque(maxlen=100)
        self.pickups = {"coin-1": (2.75, 2.0, 10)}

    def _remove_idle(self):
        now = self.clock()
        for token, player_id in list(self.sessions.items()):
            if now - self.players[player_id].last_seen > 120:
                del self.sessions[token]
                del self.players[player_id]

    def join(self, name):
        if not isinstance(name, str) or not 1 <= len(name) <= 24 or not name.isprintable():
            raise ActionRejected("Name must contain 1..24 printable characters")
        with self.lock:
            self._remove_idle()
            if len(self.players) >= 16:
                raise ActionRejected("Demo arena is full")
            index = len(self.players)
            player_id, token = secrets.token_hex(12), secrets.token_urlsafe(32)
            now = self.clock()
            player = Player(player_id, name, 2.0 + index % 4 * 1.5, 2.0 + index // 4 * 1.5,
                            budget_time=now, last_seen=now)
            self.players[player_id] = player
            self.sessions[token] = player_id
            return {"player_id": player_id, "session": token, "next_sequence": 1}

    def _session(self, token):
        if not isinstance(token, str) or token not in self.sessions:
            raise ActionRejected("Invalid match session")
        player = self.players[self.sessions[token]]
        if self.clock() - player.last_seen > 120:
            del self.players[player.id]
            del self.sessions[token]
            raise ActionRejected("Match session expired; reconnect")
        player.last_seen = self.clock()
        return player

    @staticmethod
    def _number(value):
        if type(value) not in (int, float) or not -1 <= value <= 1 or not math.isfinite(value):
            raise ActionRejected("Movement axes must be finite numbers in [-1, 1]")
        return float(value)

    @classmethod
    def _blocked(cls, x, y):
        left, top, right, bottom = cls.WALL
        radius = 0.3
        return (not radius <= x <= 20 - radius or not radius <= y <= 20 - radius
                or left - radius <= x <= right + radius and top - radius <= y <= bottom + radius)

    @classmethod
    def _line_blocked(cls, x1, y1, x2, y2):
        # Slab intersection against the wall rectangle: any segment crossing is blocked.
        low, high = 0.0, 1.0
        for origin, delta, minimum, maximum in (
            (x1, x2 - x1, cls.WALL[0], cls.WALL[2]),
            (y1, y2 - y1, cls.WALL[1], cls.WALL[3])):
            if abs(delta) < 1e-12:
                if origin < minimum or origin > maximum:
                    return False
            else:
                near, far = sorted(((minimum - origin) / delta, (maximum - origin) / delta))
                low, high = max(low, near), min(high, far)
                if low > high:
                    return False
        return True

    def advance(self):
        with self.lock:
            now = self.clock()
            count = max(0, int((now - self.last_time + 1e-9) / self.TICK))
            if not count:
                return
            # Drop excessive backlog after a stalled server; never grant huge movement jumps.
            self.last_time += count * self.TICK
            for _ in range(min(count, 5)):
                self.tick += 1
                for player in self.players.values():
                    if player.hp <= 0:
                        continue
                    if player.reload_end and self.tick >= player.reload_end:
                        player.ammo, player.reload_end = 6, 0
                    if self.tick <= player.input_until:
                        x = player.x + player.dx * self.SPEED * self.TICK
                        y = player.y + player.dy * self.SPEED * self.TICK
                        if not self._blocked(x, player.y): player.x = x
                        if not self._blocked(player.x, y): player.y = y
                    for pickup, (x, y, value) in list(self.pickups.items()):
                        if math.hypot(player.x - x, player.y - y) <= 0.35:
                            player.coins += value
                            del self.pickups[pickup]

    def _rate(self, player):
        now = self.clock()
        player.budget = min(40, player.budget + max(0, now - player.budget_time) * 30)
        player.budget_time = now
        if player.budget < 1:
            raise ActionRejected("Too many commands; slow down and resync")
        player.budget -= 1

    def command(self, token, sequence, action, arguments):
        with self.lock:
            player = self._session(token)
            self.advance()
            self._rate(player)
            if (type(sequence) is not int or not player.sequence < sequence <= player.sequence + 1000
                    or sequence > 2**53 - 1):
                raise ActionRejected("Duplicate, stale, or invalid command sequence")
            player.sequence = sequence
            try:
                if player.hp <= 0:
                    raise ActionRejected("Player is inactive")
                if not isinstance(arguments, dict):
                    raise ActionRejected("Expected action arguments")
                if action == "move":
                    if set(arguments) != {"dx", "dy"}:
                        raise ActionRejected("Move accepts direction only, not position or speed")
                    dx, dy = self._number(arguments["dx"]), self._number(arguments["dy"])
                    length = max(1.0, math.hypot(dx, dy))
                    player.dx, player.dy = dx / length, dy / length
                    player.input_until = self.tick + 5
                elif action == "attack":
                    if set(arguments) != {"target"} or not isinstance(arguments["target"], str):
                        raise ActionRejected("Attack accepts target only, not damage or health")
                    target = self.players.get(arguments["target"])
                    if not target or target.id == player.id or target.hp <= 0:
                        raise ActionRejected("Invalid target")
                    if player.reload_end or player.ammo <= 0:
                        raise ActionRejected("Reload required or in progress")
                    if self.tick < player.next_attack:
                        raise ActionRejected("Attack cooldown has not finished")
                    if math.hypot(target.x - player.x, target.y - player.y) > self.RANGE:
                        raise ActionRejected("Target is out of range")
                    if self._line_blocked(player.x, player.y, target.x, target.y):
                        raise ActionRejected("Attack is blocked by a wall")
                    player.ammo -= 1
                    player.next_attack = self.tick + self.COOLDOWN
                    target.hp = max(0, target.hp - self.DAMAGE)
                elif action == "reload":
                    if arguments or player.reload_end or player.ammo == 6:
                        raise ActionRejected("Invalid reload")
                    player.reload_end = self.tick + self.RELOAD
                else:
                    raise ActionRejected("Unsupported action; stats and rewards are server-controlled")
                return self._snapshot(player)
            except ActionRejected as exc:
                # A rejection is an observation, not proof warranting an automatic ban.
                self.events.append({"player": player.id, "tick": self.tick, "reason": str(exc)})
                raise

    def _snapshot(self, player):
        return {"tick": self.tick, "you": player.id, "next_sequence": player.sequence + 1,
                "players": [{"id": p.id, "name": p.name, "x": round(p.x, 4), "y": round(p.y, 4),
                             "hp": p.hp, "ammo": p.ammo, "coins": p.coins,
                             "reloading": bool(p.reload_end)} for p in self.players.values()],
                "pickups": [{"id": key, "x": value[0], "y": value[1]} for key, value in self.pickups.items()]}

    def state(self, token):
        with self.lock:
            player = self._session(token)
            self.advance()
            self._rate(player)
            return self._snapshot(player)
