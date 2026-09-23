# Devil-Anti-Cheat

**Version:** 0.1

Devil-Anti-Cheat is a lightweight, basic anti-cheat system designed specifically for **indie games and solo/small development teams**. It is not built for, nor intended to be used by, large-scale commercial game studios.

---

### Purpose & Scope

- **Target Audience:** Indie games needing an accessible, lightweight layer of protection.
- **Basic Protection:** Designed to mitigate common, low-effort exploits and provide basic client integrity and network checks.
- **Realistic Limitations:** This system is **not immune to attacks**. Cheating, reverse engineering, and bypasses can still occur. No client-side or basic anti-cheat can completely prevent dedicated bad actors or advanced reverse-engineering techniques.

---

### Core Modules

- **Integrity (`devil_anticheat/integrity.py`):** Basic client-side checks and validation.
- **Network (`devil_anticheat/network.py`):** Basic monitoring for network anomalies.
- **Arena (`devil_anticheat/arena.py`):** Basic session/match-level tracking.

---

### Getting Started

#### Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
