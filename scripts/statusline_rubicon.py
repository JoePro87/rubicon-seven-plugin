#!/usr/bin/env python3
"""Rubicon Seven statusline. Usage: statusline_rubicon.py [campaign_dir]
Campaign dir defaults to $RUBICON_CAMPAIGN_DIR. Prints ONE line; always exits 0.
Register in the CAMPAIGN repo's .claude/settings.json:
  "statusLine": {"type": "command",
    "command": "<venv-python> <engine>/scripts/statusline_rubicon.py"}
"""
import json, os, sys

def _dashboard_running():
    """True/False if we can tell whether the companion dashboard is running;
    None when undeterminable (no /proc, e.g. native Windows) — never guess.
    Detection is read-only by design: the dashboard writes nothing (a proven
    property), so we look at the process table, not a marker file."""
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    if b"dashboard.py" in f.read():
                        return True
            except OSError:
                continue
        return False
    except Exception:
        return None

def _last_event_bit(v):
    """Most recent mechanical delta, compact, for the line end (e.g. '[Creenash
    -7]'). None when there are none. Self-contained: the statusline imports only
    json/os/sys, so the enemy qualitative thresholds are inlined here (they
    mirror mechanics_ticker._enemy_word) rather than importing the repo."""
    evs = v.get("last_events") or []
    if not evs:
        return None
    e = evs[-1]
    k, nm = e.get("kind"), e.get("name", "?")
    if k == "pc_damage":
        return f"[{nm} -{e.get('amount')}]"
    if k == "pc_heal":
        return f"[{nm} +{e.get('amount')}]"
    if k == "enemy_damage":
        # Stored events carry the quantized word (record_events strips pct so
        # the player-facing ledger never holds the exact fraction).
        word = e.get("state")
        if not word:
            p = e.get("pct", 0)
            word = ("unharmed" if p >= 1 else "hurt" if p > 0.5
                    else "bloodied" if p > 0 else "down")
        return f"[{nm}: {word}]"
    if k == "enemy_ability":
        return f"[{nm} weakened]"
    if k == "condition":
        return f"[{nm} {'+' if e.get('applied') else '-'}{e.get('condition')}]"
    if k == "wound":
        return f"[{nm} wound]"
    if k == "ability_damage":
        return f"[{nm} -{e.get('amount')}{e.get('stat')}]"
    return None


def _context_bit():
    """Context-window element from the JSON Claude Code pipes on stdin.
    Returns e.g. 'ctx 37% left', or None when stdin is absent or the
    percentage is null (manual runs, pre-first-API-call, right after
    /compact) — omit rather than show a bogus number."""
    try:
        if sys.stdin.isatty():
            return None
        pct = (json.load(sys.stdin).get("context_window") or {}).get("remaining_percentage")
        if pct is None:
            return None
        return f"ctx {round(pct)}% left"
    except Exception:
        return None

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ctx = _context_bit()
    try:
        camp = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("RUBICON_CAMPAIGN_DIR", "")
        with open(os.path.join(camp, "player_view.json"), encoding="utf-8") as f:
            v = json.load(f)
    except Exception:
        print("Rubicon Seven — no live view" + (f" │ {ctx}" if ctx else ""))
        return
    bits = [f"Day {v.get('day', '?')}"]
    if v.get("weather"):
        bits[0] += f" · {v['weather']}"
    if v.get("location"):
        bits.append(v["location"])
    def _pc_seg(p):
        seg = f"{p.get('name')} {p.get('hp')}/{p.get('hp_max')}"
        nc = len(p.get("conditions") or [])
        if nc:
            seg += f"!{nc}c"
        return seg
    party = " · ".join(_pc_seg(p) for p in v.get("party", []) if p.get("name"))
    if party:
        bits.append(party)
    supply = (v.get("supply") or {}).get("mode")
    if supply:
        bits.append(f"supply {supply}")
    if v.get("in_combat"):
        bits.append("⚔ COMBAT")
    n = len(v.get("open_parleys") or [])
    if n:
        bits.append(f"🤝 {n}")
    ev = _last_event_bit(v)
    if ev:
        bits.append(ev)
    if ctx:
        bits.append(ctx)
    if _dashboard_running() is False:
        bits.append(f"▸ {os.environ.get('RUBICON_DASH_HINT', 'dash: scripts/dashboard.py')}")
    print(" │ ".join(bits))

if __name__ == "__main__":
    main()
