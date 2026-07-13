"""W2 — Context-budget tripwires: the knowledge layer must not decay silently.

Born from the 2026-06-12 audit: campaign MEMORY.md grew past its 200-line auto-load
window and silently truncated; the DM-screen Tensions block accreted to 4,557 chars
(~1.1k tokens every turn); "PENDING X" flags sat stale for a week. The game-state
layer already alarms (ticks, clocks, nags) — these tests pin the same fired!=surfaced
pattern onto the always-on files.
"""
import datetime

from hooks.session_verify import check_budgets, check_staleness


def _campaign(tmp_path, dm_screen="## PARTY\nx\n", claude_md="protocol\n"):
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    for f in ["WORLD_PROGRESS.md", "RESONANCE_INDEX.md", "MASTER_CONTINUITY_CURRENT.md"]:
        (campaign / f).write_text("x", encoding="utf-8")
    (campaign / "VAARN_DM_SCREEN.md").write_text(dm_screen, encoding="utf-8")
    (campaign / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    return campaign


def _memory(tmp_path, lines=50):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("\n".join(["l"] * lines), encoding="utf-8")
    return memory


def _result(results, target):
    return [r for r in results if r["target"] == target][0]


# --- MEMORY.md margin: alarm BEFORE the 200-line loader cliff, not at it ---

def test_memory_at_195_lines_fails_under_190_budget(tmp_path):
    campaign = _campaign(tmp_path)
    memory = _memory(tmp_path, lines=195)
    r = _result(check_budgets(campaign, memory), "MEMORY.md")
    assert r["ok"] is False
    assert "190" in r["detail"]


def test_memory_at_190_lines_passes(tmp_path):
    campaign = _campaign(tmp_path)
    memory = _memory(tmp_path, lines=190)
    r = _result(check_budgets(campaign, memory), "MEMORY.md")
    assert r["ok"] is True


def test_missing_memory_file_fails_not_silently_passes(tmp_path):
    """A missing file means the check measured nothing — that must be loud, not a 0-line pass."""
    campaign = _campaign(tmp_path)
    memory = tmp_path / "MEMORY.md"  # never written
    r = _result(check_budgets(campaign, memory), "MEMORY.md")
    assert r["ok"] is False
    assert "not found" in r["detail"]


# --- DM-screen Tensions block char budget (the 4,557-char bloat hid inside a file
#     comfortably under its LINE budget) ---

def test_tensions_block_over_2500_chars_fails(tmp_path):
    bullets = "\n".join(f"- tension {i}: " + "x" * 80 for i in range(40))
    screen = "## PARTY\np\n\n## POLITICAL WEATHER\nTensions (terse):\n" + bullets + "\n\n## QUICK GENERATORS\ng\n"
    campaign = _campaign(tmp_path, dm_screen=screen)
    memory = _memory(tmp_path)
    r = _result(check_budgets(campaign, memory), "VAARN_DM_SCREEN.md Tensions")
    assert r["ok"] is False
    assert "2500" in r["detail"]


def test_tensions_block_under_budget_passes(tmp_path):
    screen = "## POLITICAL WEATHER\nTensions (terse):\n- one\n- two\n\n## QUICK GENERATORS\ng\n"
    campaign = _campaign(tmp_path, dm_screen=screen)
    memory = _memory(tmp_path)
    r = _result(check_budgets(campaign, memory), "VAARN_DM_SCREEN.md Tensions")
    assert r["ok"] is True


def test_no_tensions_block_is_ok_not_crash(tmp_path):
    campaign = _campaign(tmp_path, dm_screen="## PARTY\nx\n")
    memory = _memory(tmp_path)
    results = check_budgets(campaign, memory)
    targets = [r["target"] for r in results]
    assert "VAARN_DM_SCREEN.md Tensions" not in targets  # nothing to measure, no false alarm


def test_tensions_measures_only_to_next_section(tmp_path):
    """The QUICK GENERATORS section after Tensions must not count toward the Tensions budget."""
    screen = ("## POLITICAL WEATHER\nTensions:\n- small\n\n## QUICK GENERATORS\n"
              + "x" * 5000 + "\n")
    campaign = _campaign(tmp_path, dm_screen=screen)
    memory = _memory(tmp_path)
    r = _result(check_budgets(campaign, memory), "VAARN_DM_SCREEN.md Tensions")
    assert r["ok"] is True


# --- Campaign CLAUDE.md size (imported EVERY turn; warn-only — protocol edits are
#     deliberate, not save-time accretion) ---

def test_claude_md_over_8000_bytes_warns_not_fails(tmp_path):
    campaign = _campaign(tmp_path, claude_md="x" * 9000)
    memory = _memory(tmp_path)
    r = _result(check_budgets(campaign, memory), "CLAUDE.md")
    assert r["ok"] is True  # warn-only never blocks the save
    assert r["warn"] is True


def test_claude_md_under_budget_no_warn(tmp_path):
    campaign = _campaign(tmp_path, claude_md="x" * 1000)
    memory = _memory(tmp_path)
    r = _result(check_budgets(campaign, memory), "CLAUDE.md")
    assert r["ok"] is True
    assert r["warn"] is False


# --- Staleness scan: PENDING notes must carry a check-by date and not be past it ---

def test_pending_without_check_by_warns(tmp_path):
    campaign = _campaign(tmp_path)
    memory = tmp_path / "MEMORY.md"
    memory.write_text("- thing X PENDING an MCP restart\n", encoding="utf-8")
    results = check_staleness(campaign, memory, current_day=130)
    r = _result(results, "staleness")
    assert r["warn"] is True
    assert "check-by" in r["detail"]


def test_pending_with_future_date_is_clean(tmp_path):
    campaign = _campaign(tmp_path)
    memory = tmp_path / "MEMORY.md"
    future = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
    memory.write_text(f"- thing X PENDING restart (check-by {future})\n", encoding="utf-8")
    results = check_staleness(campaign, memory, current_day=130)
    r = _result(results, "staleness")
    assert r["warn"] is False


def test_pending_with_past_date_warns(tmp_path):
    campaign = _campaign(tmp_path)
    memory = tmp_path / "MEMORY.md"
    memory.write_text("- thing X PENDING restart (check-by 2026-01-01)\n", encoding="utf-8")
    results = check_staleness(campaign, memory, current_day=130)
    r = _result(results, "staleness")
    assert r["warn"] is True
    assert "past" in r["detail"]


def test_pending_with_campaign_day_form(tmp_path):
    campaign = _campaign(tmp_path)
    memory = tmp_path / "MEMORY.md"
    memory.write_text("- wind the failsafe clocks PENDING (check-by D129)\n", encoding="utf-8")
    results = check_staleness(campaign, memory, current_day=130)
    r = _result(results, "staleness")
    assert r["warn"] is True  # D129 < current day 130 = past due


def test_lowercase_pending_in_prose_is_ignored(tmp_path):
    """Only the ALL-CAPS PENDING marker is a flag; prose 'pending' must not false-positive."""
    campaign = _campaign(tmp_path)
    memory = tmp_path / "MEMORY.md"
    memory.write_text("- the case is pending review with the council\n", encoding="utf-8")
    results = check_staleness(campaign, memory, current_day=130)
    r = _result(results, "staleness")
    assert r["warn"] is False


def test_staleness_scans_dm_screen_too(tmp_path):
    screen = "## PARTY\nx\n- old note PENDING cleanup\n"
    campaign = _campaign(tmp_path, dm_screen=screen)
    memory = _memory(tmp_path)
    results = check_staleness(campaign, memory, current_day=130)
    r = _result(results, "staleness")
    assert r["warn"] is True


# --- Wired into run_verification so it actually fires at session-end ---

def test_run_verification_includes_staleness_and_claude_md(tmp_path):
    import json
    from hooks.session_verify import run_verification
    from hooks.fabrication_bans import FabricationBans
    from hooks.distillation_cache import DistillationCache

    facts = {"run_started_at": "2026-06-12T14:00:00", "day": 130, "beats": [],
             "locations_touched": [], "escalations": [],
             "scratchpad_routed": {"cultivation_seeds": []},
             "memory_flags": {"consolidation_needed": False}}
    facts_path = tmp_path / "session_end_facts.json"
    facts_path.write_text(json.dumps(facts), encoding="utf-8")
    campaign = _campaign(tmp_path)
    memory = _memory(tmp_path)
    bans = FabricationBans(tmp_path / "bans.json")
    cache = DistillationCache(tmp_path / "cache.json")

    report = run_verification(facts_path, campaign, memory, bans, cache,
                              current_status_day=130, pass_number=1)
    targets = [c["target"] for c in report["checks"]]
    assert "staleness" in targets
    assert "CLAUDE.md" in targets
