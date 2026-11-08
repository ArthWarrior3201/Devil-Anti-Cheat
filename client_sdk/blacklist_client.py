"""
devil.blacklist_client — configurable client for a company's blacklist server.

Lets a company wire Devil's launch check to THEIR backend without touching
code. All transport details come from an optional protocol config file
(devil_protocol.json); sensible defaults apply when it's absent.

Config (every field optional):
{
  "endpoint":    "https://ac.company.com/v1/check",
  "method":      "POST",                 // or "GET"
  "auth":        {"type": "bearer", "token": "..."},   // none|header|bearer
  "request":     {"hwid_field": "hwid", "static": {"title": "acme-fps"}},
  "response":    {"banned_path": "data.banned", "reason_path": "data.reason"},
  "timeout_s":   4.0,
  "retries":     2,
  "verify_tls":  true,
  "fail_mode":   "open"                   // open = allow if server unreachable
}

The transport is injectable so this is testable offline; by default it uses
urllib over HTTPS with TLS verification on.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import json
import time
import urllib.request
import urllib.error
import urllib.parse


DEFAULTS = {
    "endpoint": "https://localhost/v1/check",
    "method": "POST",
    "auth": {"type": "none"},
    "request": {"hwid_field": "hwid", "static": {}},
    "response": {"banned_path": "banned", "reason_path": "reason"},
    "timeout_s": 4.0,
    "retries": 2,
    "verify_tls": True,
    "fail_mode": "open",
}


def _dig(obj, dotted, default=None):
    cur = obj
    for key in dotted.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def load_config(path: str | None) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))   # deep copy
    if path:
        try:
            with open(path) as f:
                user = json.load(f)
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except FileNotFoundError:
            pass   # defaults stand
    return cfg


@dataclass
class CheckResult:
    banned: bool
    reason: str = ""
    ok: bool = True          # False => could not reach/parse server
    note: str = ""


def _default_transport(req_url, payload, headers, method, timeout, verify_tls):
    """Real HTTPS transport. Raises urllib errors on failure."""
    import ssl
    ctx = ssl.create_default_context()
    if not verify_tls:               # the config can relax this; default is on
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    data = json.dumps(payload).encode() if method == "POST" else None
    url = req_url
    if method == "GET":
        url = req_url + "?" + urllib.parse.urlencode(payload)
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode())


class BlacklistClient:
    def __init__(self, config: dict, transport=None):
        self.cfg = config
        self._transport = transport or _default_transport

    def _headers(self):
        h = {"Content-Type": "application/json"}
        auth = self.cfg.get("auth", {})
        if auth.get("type") == "bearer":
            h["Authorization"] = f"Bearer {auth.get('token','')}"
        elif auth.get("type") == "header":
            h[auth.get("name", "X-API-Key")] = auth.get("value", "")
        return h

    def check(self, hwid: str) -> CheckResult:
        cfg = self.cfg
        payload = dict(cfg["request"].get("static", {}))
        payload[cfg["request"].get("hwid_field", "hwid")] = hwid
        last_err = None
        for attempt in range(cfg.get("retries", 2) + 1):
            try:
                body = self._transport(
                    cfg["endpoint"], payload, self._headers(),
                    cfg.get("method", "POST"), cfg.get("timeout_s", 4.0),
                    cfg.get("verify_tls", True))
                banned = bool(_dig(body, cfg["response"]["banned_path"], False))
                reason = str(_dig(body, cfg["response"]["reason_path"], "") or "")
                return CheckResult(banned, reason, ok=True)
            except Exception as e:              # network/TLS/parse problem
                last_err = e
                time.sleep(0.05 * (attempt + 1))
        # Could not reach the server: apply the company's fail policy.
        if cfg.get("fail_mode", "open") == "closed":
            return CheckResult(True, "server unreachable (fail-closed)",
                               ok=False, note=str(last_err))
        return CheckResult(False, "", ok=False,
                           note=f"server unreachable (fail-open): {last_err}")
