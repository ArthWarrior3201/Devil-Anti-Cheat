"""
devil.vmsignal — VM / sandbox detection as a REPORT-ONLY signal.

This is the collectable part of "VM protection". It answers "does this look
like a VM?" and returns a structured verdict with a confidence score. It never
blocks, kills, or persists — the detection backend scores it as ONE input.

Honest ceiling: this is a weak, spoofable signal. A well-configured hypervisor
hides every artifact here. Score it server-side alongside other evidence; never
enforce on it alone. The unspoofable version of this goal is hardware
attestation (TPM 2.0 measured boot), which is a separate, non-rootkit build.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import os
import platform
import re
import uuid

VM_MAC_PREFIXES = {
    "00:05:69": "VMware", "00:0c:29": "VMware", "00:1c:14": "VMware",
    "00:50:56": "VMware", "08:00:27": "VirtualBox", "0a:00:27": "VirtualBox",
    "00:16:3e": "Xen", "00:1c:42": "Parallels", "00:15:5d": "Hyper-V",
    "52:54:00": "QEMU/KVM",
}
_CHECK_WEIGHTS = {"cpu_hypervisor_flag": 0.45, "hypervisor_vendor": 0.30}


@dataclass
class VMSignal:
    checks: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)

    def record(self, name, hit, detail=""):
        self.checks[name] = (bool(hit), detail)

    def unavailable(self, name, why):
        self.errors[name] = why

    @property
    def hits(self):
        return [n for n, (h, _) in self.checks.items() if h]

    @property
    def confidence(self):
        if not self.checks:
            return 0.0
        score = sum(_CHECK_WEIGHTS.get(n, 0.12)
                    for n, (h, _) in self.checks.items() if h)
        return min(1.0, round(score, 3))

    def as_report(self):
        return {
            "likely_vm": self.confidence >= 0.5,
            "confidence": self.confidence,
            "hits": self.hits,
            "checks": {n: {"hit": h, "detail": d}
                       for n, (h, d) in self.checks.items()},
            "unavailable": self.errors,
            "note": "weak signal; score server-side, do not enforce locally",
        }


def _cpu_hypervisor_flag(sig):
    try:
        if platform.system() == "Linux" and os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo") as f:
                hit = bool(re.search(r"^flags\s*:.*\bhypervisor\b",
                                     f.read(), re.M))
            sig.record("cpu_hypervisor_flag", hit,
                       "hypervisor flag set" if hit else "no hypervisor flag")
        else:
            sig.unavailable("cpu_hypervisor_flag", "needs CPUID on this OS")
    except Exception as e:
        sig.unavailable("cpu_hypervisor_flag", f"{type(e).__name__}: {e}")


def _hypervisor_vendor(sig):
    try:
        blob = ""
        for p in ("/sys/class/dmi/id/product_name",
                  "/sys/class/dmi/id/sys_vendor",
                  "/sys/class/dmi/id/bios_vendor"):
            try:
                with open(p) as f:
                    blob += f.read() + " "
            except Exception:
                pass
        found = None
        for needle, name in [("vmware", "VMware"), ("virtualbox", "VirtualBox"),
                             ("innotek", "VirtualBox"), ("qemu", "QEMU"),
                             ("xen", "Xen"), ("kvm", "KVM"),
                             ("parallels", "Parallels")]:
            if needle in blob.lower():
                found = name
                break
        if blob.strip():
            sig.record("hypervisor_vendor", found is not None,
                       f"DMI -> {found}" if found else "DMI looks physical")
        else:
            sig.unavailable("hypervisor_vendor", "no DMI/CPUID access")
    except Exception as e:
        sig.unavailable("hypervisor_vendor", f"{type(e).__name__}: {e}")


def _mac_oui(sig):
    try:
        node = uuid.getnode()
        mac = ":".join(f"{(node >> e) & 0xff:02x}" for e in range(40, -8, -8))
        vendor = VM_MAC_PREFIXES.get(mac[:8])
        sig.record("mac_oui", vendor is not None,
                   f"{mac} -> {vendor}" if vendor else f"{mac}")
    except Exception as e:
        sig.unavailable("mac_oui", f"{type(e).__name__}: {e}")


def _low_core_count(sig):
    try:
        n = os.cpu_count() or 0
        sig.record("low_core_count", 0 < n <= 2, f"{n} logical CPUs")
    except Exception as e:
        sig.unavailable("low_core_count", f"{type(e).__name__}: {e}")


def _vm_device_files(sig):
    try:
        found = [p for p in ("/dev/vboxguest", "/dev/vboxuser", "/dev/vmci")
                 if os.path.exists(p)]
        sig.record("vm_device_files", bool(found),
                   ", ".join(found) if found else "none")
    except Exception as e:
        sig.unavailable("vm_device_files", f"{type(e).__name__}: {e}")


def collect() -> VMSignal:
    sig = VMSignal()
    for check in (_cpu_hypervisor_flag, _hypervisor_vendor, _mac_oui,
                  _low_core_count, _vm_device_files):
        check(sig)
    return sig
