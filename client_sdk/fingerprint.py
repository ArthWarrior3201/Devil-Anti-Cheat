"""
devil.fingerprint — user-mode hardware fingerprint collection.

Reads the stable hardware identifiers a launcher folds into one HWID hash:
CPU, OS build, disk, MAC, etc. USER MODE: no kernel driver. On Linux it reads
/proc and /sys; the Windows sources (WMI / registry / CPUID) are named in
comments and guarded so the module runs anywhere.

Honest limitation — read this before thinking you need a kernel driver:
    User-mode reads can be spoofed by a determined cheat who hooks the same
    APIs. That is the real argument for a kernel-mode reader (what Vanguard
    does), and it's also why you DON'T hand-roll one: a kernel anti-cheat
    driver needs an EV cert + Microsoft attestation signing to load at all, a
    bug in it bluescreens every player, and a weak one is a system-wide
    security hole. The correct sequence for an indie build is: ship user-mode
    collection + the server-authoritative core first (which already blocks the
    gameplay cheats), measure, and only later add a professionally-audited,
    signed kernel reader if the economics justify it. This module is that
    first, safe layer.

Never collects the OS activation key or any license secret.
"""

from __future__ import annotations
import hashlib
import os
import platform
import re
import uuid


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None


def collect() -> dict:
    """Best-effort hardware identifiers. Missing fields are reported, not faked."""
    comp: dict[str, str] = {}
    missing: list[str] = []

    # --- CPU -------------------------------------------------------------
    # Windows: WMI Win32_Processor.ProcessorId / registry. Linux: /proc/cpuinfo.
    cpu = None
    info = _read("/proc/cpuinfo")
    if info:
        m = re.search(r"^model name\s*:\s*(.+)$", info, re.M)
        if m:
            cpu = m.group(1)
    cpu = cpu or (platform.processor() or None)
    if cpu:
        comp["cpu"] = cpu
    else:
        missing.append("cpu")

    # --- OS build --------------------------------------------------------
    # Windows: CurrentBuildNumber (26200 etc). Here: platform build string.
    build = platform.version() or platform.release()
    if build:
        comp["os_build"] = build
    else:
        missing.append("os_build")

    # --- disk ------------------------------------------------------------
    # Windows: WMI Win32_DiskDrive.SerialNumber. Linux: /sys block serial.
    disk = None
    try:
        for dev in sorted(os.listdir("/sys/block")):
            s = _read(f"/sys/block/{dev}/serial")
            if s:
                disk = s
                break
    except Exception:
        pass
    if disk:
        comp["disk"] = disk
    else:
        missing.append("disk")

    # --- GPU (best effort) ----------------------------------------------
    # Windows: WMI Win32_VideoController. Linux: lspci text if present.
    gpu = _read("/proc/driver/nvidia/gpus") or None
    if gpu:
        comp["gpu"] = gpu

    # --- MAC -------------------------------------------------------------
    try:
        node = uuid.getnode()
        comp["mac"] = ":".join(f"{(node >> e) & 0xff:02x}"
                               for e in range(40, -8, -8))
    except Exception:
        missing.append("mac")

    return {"components": comp, "missing": missing}


def fingerprint_hash(components: dict, deployment_salt: str) -> str:
    """One opaque digest over the sorted components. Raw values stay on-device."""
    parts = "|".join(f"{k}={components[k]}" for k in sorted(components))
    return hashlib.sha256((deployment_salt + "|" + parts).encode()).hexdigest()
