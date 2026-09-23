"""Local reference match server and HTTPS-capable integration client."""
from collections import deque
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.parse import urlsplit
from urllib.error import URLError
from .arena import Arena, ActionRejected

MAX_MESSAGE = 32768


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("Invalid numeric constant")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


class MatchServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, arena, port=8766):
        self.arena = arena
        self.join_times = deque(maxlen=32)
        self.stop_event = threading.Event()
        super().__init__(("127.0.0.1", port), Handler)
        self.ticker = threading.Thread(target=self._tick, daemon=True)
        self.ticker.start()

    def _tick(self):
        while not self.stop_event.wait(Arena.TICK):
            self.arena.advance()

    def server_close(self):
        self.stop_event.set()
        self.ticker.join(timeout=1)
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, *_):
        pass

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_MESSAGE: raise ValueError("Invalid request size")
            data = parse(self.rfile.read(size))
            if not isinstance(data, dict): raise ValueError("Expected JSON object")
            arena = self.server.arena
            if self.path == "/join" and set(data) == {"name"}:
                with arena.lock:
                    now = time.monotonic()
                    times = self.server.join_times
                    while times and times[0] < now - 60: times.popleft()
                    if len(times) >= 32: raise ActionRejected("Too many joins; retry later")
                    times.append(now)
                    result = arena.join(data["name"])
            elif self.path == "/command" and set(data) == {"session", "sequence", "action", "arguments"}:
                result = arena.command(data["session"], data["sequence"], data["action"], data["arguments"])
            elif self.path == "/state" and set(data) == {"session"}:
                result = arena.state(data["session"])
            else:
                raise ActionRejected("Unknown endpoint or unsupported request fields")
            response = {"ok": True, "result": result}
        except (ActionRejected, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            response = {"ok": False, "error": str(exc)[:160]}
        except OSError:
            return
        raw = json.dumps(response, allow_nan=False).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except OSError:
            pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ActionRejected("Unexpected match-server redirect")


class MatchClient:
    def __init__(self, url, development_http=False):
        parts = urlsplit(url)
        if (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
                or parts.path not in ("", "/")):
            raise ValueError("Use a clean match-server origin URL")
        if parts.scheme != "https" and not (parts.scheme == "http" and development_http
                and parts.hostname in ("127.0.0.1", "localhost", "::1")):
            raise ValueError("HTTPS required except explicitly enabled loopback development HTTP")
        self.url = url.rstrip("/")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.session = None
        self.sequence = 1
        self.player_id = None

    def post(self, route, data):
        raw = json.dumps(data, allow_nan=False).encode()
        if len(raw) > MAX_MESSAGE: raise ActionRejected("Request too large")
        try:
            with self.opener.open(Request(self.url + route, data=raw,
                    headers={"Content-Type": "application/json"}), timeout=3) as response:
                raw = response.read(MAX_MESSAGE + 1)
        except (URLError, OSError) as exc:
            raise ActionRejected("Match server unavailable; reconnect or retry") from exc
        if len(raw) > MAX_MESSAGE: raise ActionRejected("Reply too large")
        result = parse(raw)
        if result.get("ok") is not True: raise ActionRejected(result.get("error", "Action refused"))
        return result["result"]

    def join(self, name):
        result = self.post("/join", {"name": name})
        self.session, self.player_id = result["session"], result["player_id"]
        self.sequence = result["next_sequence"]
        return result

    def command(self, action, **arguments):
        sequence = self.sequence
        self.sequence += 1  # Use state() to resync after a dropped response.
        return self.post("/command", {"session": self.session, "sequence": sequence,
                         "action": action, "arguments": arguments})

    def state(self):
        result = self.post("/state", {"session": self.session})
        self.sequence = result["next_sequence"]
        return result
