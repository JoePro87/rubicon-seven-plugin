#!/usr/bin/env python3
"""Session-mode volume: run all cases SEQUENTIALLY with the delta-fold ACTIVE
(fold NOT reset between cases, turn_count increments) -- i.e. how check_canon
actually behaves across a continuous session in the same scene. Contrast with
canon_recall_live.py which resets the fold per case (worst-case fresh).

*** THIS SCRIPT WRITES hooks/.hook_state.json WHILE IT RUNS. ***
It overwrites the LIVE hook state turn-by-turn to drive check_canon through the
whole case bed in one simulated session, then restores the pre-run state at the
end. Do not run this against a hook_state a live gameplay session is using.

Takes no arguments beyond --help; runs the full case bed unconditionally.

MUST run under the Windows venv (chromadb 1.3.7):
    .venv/Scripts/python.exe scripts/canon_session_volume.py
"""
import argparse
import sys, json
from pathlib import Path

_parser = argparse.ArgumentParser(
    description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="WARNING: writes hooks/.hook_state.json (repeatedly, then restores it at "
           "the end). Do not run this against a hook_state a live session is using.")
_parser.parse_args()  # no options beyond -h/--help; exits before any state write

print(f"WARNING: WRITING hooks/.hook_state.json repeatedly (per-turn session simulation), "
      f"then restoring it at the end. Do not run this against a hook_state a live "
      f"session is using.", file=sys.stderr)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server
import rubicon_paths
import scripts.canon_recall_gate as crg
# canon_recall_gate.py now defaults MCP/CAMP via rubicon_paths itself; this
# monkeypatch is redundant on the standard sibling layout but kept explicit so
# an env-var override (RUBICON_ENGINE_DIR / RUBICON_CAMPAIGN_DIR) applies here too.
crg.MCP = rubicon_paths.engine_dir()
crg.CAMP = rubicon_paths.campaign_dir()

HS = server.HOOK_STATE_FILE
base = json.loads(HS.read_text())
cases = crg.load_cases()

st = dict(base)
st.update({"canon_delivered": {}, "last_canon_hash": None,
           "canon_block_hashes": {}, "last_canon_turn": 0, "turn_count": 1})
HS.write_text(json.dumps(st))

tot = 0
first = None
for i, c in enumerate(cases):
    s = json.loads(HS.read_text())
    s["turn_count"] = i + 1
    HS.write_text(json.dumps(s))
    o = server.check_canon(None, user_input=c["input"], needs=[], auto_correct_prep=False)
    t = len(o) // 4
    tot += t
    if i == 0:
        first = t

HS.write_text(json.dumps(base))  # restore live state
n = len(cases)
print("SESSION-MODE (delta-fold ACTIVE, scene stable):")
print(f"  turn 1 cold: {first} tok | mean over {n} turns: {tot//n} | total {tot:,}")
print(f"  worst-case (fold reset/turn) mean was 1896 -> session-mode mean {tot//n}")
