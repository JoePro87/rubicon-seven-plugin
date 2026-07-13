"""Non-canon sandbox smoke for the World Tick (real code paths, real dice).

MUST run with RUBICON_CAMPAIGN_DIR pointed at sandbox-campaign/ -- the
runner below sets it before importing server. Exercises the full clock
lifecycle and the arrival-stamp return check end to end:

  wind -> advance_day (multi-day, fires once) -> fired-guard -> briefing
  shows FIRED-UNSURFACED twice -> development surfaces it -> resolve;
  arrive -> re-arrive across an 8-day gap -> changes push.

Usage:
  .venv/Scripts/python.exe scripts/smoke_world_tick.py
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SANDBOX = REPO_ROOT / "sandbox-campaign"
assert SANDBOX.exists(), "run scripts/make_sandbox.py first"
os.environ["RUBICON_CAMPAIGN_DIR"] = str(SANDBOX)

sys.path.insert(0, str(REPO_ROOT))
import server  # noqa: E402  (env must be set first)

FAILS = []


def check(label, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + label + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILS.append(label)


print("=== current day ===")
day0 = server._thread_current_day()
print("sandbox day:", day0)

print("\n=== 1. wind a clock due day+2 ===")
out = server.thread(action="add", thread_id="smoke-vacuum",
                    title="THREAT: smoke vacuum",
                    description="sandbox-only world-tick smoke thread",
                    clock_due_day=day0 + 2, clock_label="smoke vacuum ripens")
print(out)
check("wind reports clock", "Clock wound" in out)

print("\n=== 2. advance_day +3 (jump past due) ===")
out = server.advance_day(day0 + 3, "world-tick smoke jump")
print(out)
check("WORLD TICK block", "WORLD TICK" in out)
check("label in tick", "smoke vacuum ripens" in out)
check("thread get push", 'thread(action="get", thread_id="smoke-vacuum")' in out)
check("canon pull push", "search_campaign_history" in out)

print("\n=== 3. advance_day +1 more (fired-guard) ===")
out = server.advance_day(day0 + 4, "world-tick smoke guard")
check("no second fire", "smoke vacuum ripens" not in out)

print("\n=== 4. briefing shows FIRED-UNSURFACED (twice) ===")
b1 = server.full_session_startup()
b2 = server.full_session_startup()
for n, b in (("first", b1), ("second", b2)):
    sec = "WORLD FORCES" in b and "NOT YET SURFACED" in b and "smoke vacuum ripens" in b
    check(f"{n} briefing nags", sec)

print("\n=== 5. development surfaces it ===")
out = server.thread(action="update", thread_id="smoke-vacuum",
                    development="Posters name a claimant; the vacuum is public.")
print(out)
b3 = server.full_session_startup()
check("surfaced: line gone", "smoke vacuum ripens" not in b3)

print("\n=== 6. resolve (DM act, never engine) ===")
out = server.thread(action="resolve", thread_id="smoke-vacuum",
                    resolution="Claimant takes the seal.", resolution_day=day0 + 4)
print(out)
check("resolved", "resolved" in out.lower())

print("\n=== 7. arrive / re-arrive across 8-day gap ===")
out = server.supply(action="arrive", location="Gnomon")
print(out)
check("first arrive: no changes push", "rulebook" not in out)
out = server.advance_day(day0 + 12, "smoke gap jump")
out = server.supply(action="arrive", location="Gnomon")
print(out)
check("gap push present", "table-changes-in-gnomon" in out)
check("gap days right", "8 days" in out)

print()
if FAILS:
    print("SMOKE FAILED:", FAILS)
    sys.exit(1)
print("SMOKE PASSED: all checks green")
