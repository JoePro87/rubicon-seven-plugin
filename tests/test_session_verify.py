"""Tests for the deterministic session-end verifier."""
import json
import os

from hooks.session_verify import check_writes_landed


def _write_facts(tmp_path, **overrides):
    facts = {
        "run_started_at": "2026-05-31T14:00:00",
        "day": 129,
        "beats": ["something happened"],
        "locations_touched": [],
        "escalations": [],
        "scratchpad_routed": {"cultivation_seeds": []},
        "memory_flags": {"consolidation_needed": False},
    }
    facts.update(overrides)
    p = tmp_path / "session_end_facts.json"
    p.write_text(json.dumps(facts), encoding="utf-8")
    return p


def _touch_after(path, ref_path):
    """Make `path` newer than `ref_path`."""
    path.write_text("updated", encoding="utf-8")
    ref_mtime = ref_path.stat().st_mtime
    os.utime(path, (ref_mtime + 10, ref_mtime + 10))


def test_always_expected_file_missing_is_flagged(tmp_path):
    facts_path = _write_facts(tmp_path)
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    memory = tmp_path / "MEMORY.md"  # exists but stale (older than facts)
    memory.write_text("old", encoding="utf-8")
    old = facts_path.stat().st_mtime - 100
    os.utime(memory, (old, old))

    result = check_writes_landed(facts_path, campaign, memory)
    flagged = [r for r in result if not r["ok"]]
    names = [r["target"] for r in flagged]
    assert "MEMORY.md" in names  # stale = not landed


def test_fresh_always_file_passes(tmp_path):
    facts_path = _write_facts(tmp_path)
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    (campaign / "WORLD_PROGRESS.md").write_text("x", encoding="utf-8")
    (campaign / "dm_narrative_synthesis.md").write_text("x", encoding="utf-8")
    (campaign / "VAARN_DM_SCREEN.md").write_text("x", encoding="utf-8")
    memory = tmp_path / "MEMORY.md"
    for f in [campaign / "WORLD_PROGRESS.md", campaign / "dm_narrative_synthesis.md",
              campaign / "VAARN_DM_SCREEN.md", memory]:
        _touch_after(f, facts_path)

    result = check_writes_landed(facts_path, campaign, memory)
    mem = [r for r in result if r["target"] == "MEMORY.md"][0]
    assert mem["ok"] is True


def test_conditional_antagonist_expected_when_escalations(tmp_path):
    facts_path = _write_facts(tmp_path, escalations=["a seed ripened"])
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    memory = tmp_path / "MEMORY.md"
    result = check_writes_landed(facts_path, campaign, memory)
    names = [r["target"] for r in result]
    assert "ANTAGONIST_CULTIVATION.md" in names
    assert "narrative_threads.json" in names


def test_conditional_skipped_when_bucket_empty(tmp_path):
    facts_path = _write_facts(tmp_path, escalations=[], locations_touched=[])
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    memory = tmp_path / "MEMORY.md"
    result = check_writes_landed(facts_path, campaign, memory)
    names = [r["target"] for r in result]
    assert "ANTAGONIST_CULTIVATION.md" not in names
    assert "prep PROGRESS LOGs" not in names


from hooks.session_verify import check_budgets


def test_budgets_pass_when_under(tmp_path):
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    (campaign / "WORLD_PROGRESS.md").write_text("x" * 100, encoding="utf-8")
    (campaign / "RESONANCE_INDEX.md").write_text("x" * 100, encoding="utf-8")
    (campaign / "VAARN_DM_SCREEN.md").write_text("\n".join(["l"] * 50), encoding="utf-8")
    (campaign / "MASTER_CONTINUITY_CURRENT.md").write_text("x" * 100, encoding="utf-8")
    memory = tmp_path / "MEMORY.md"
    memory.write_text("\n".join(["l"] * 50), encoding="utf-8")

    results = check_budgets(campaign, memory)
    assert all(r["ok"] for r in results), results


def test_world_progress_over_budget_flags(tmp_path):
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    (campaign / "WORLD_PROGRESS.md").write_text("x" * 25000, encoding="utf-8")
    (campaign / "RESONANCE_INDEX.md").write_text("x", encoding="utf-8")
    (campaign / "VAARN_DM_SCREEN.md").write_text("l", encoding="utf-8")
    (campaign / "MASTER_CONTINUITY_CURRENT.md").write_text("x", encoding="utf-8")
    memory = tmp_path / "MEMORY.md"
    memory.write_text("l", encoding="utf-8")

    results = check_budgets(campaign, memory)
    wp = [r for r in results if r["target"] == "WORLD_PROGRESS.md"][0]
    assert wp["ok"] is False
    assert "20000" in wp["detail"]


def test_dm_screen_over_line_budget_flags(tmp_path):
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    for f, content in [("WORLD_PROGRESS.md", "x"), ("RESONANCE_INDEX.md", "x"),
                       ("MASTER_CONTINUITY_CURRENT.md", "x")]:
        (campaign / f).write_text(content, encoding="utf-8")
    (campaign / "VAARN_DM_SCREEN.md").write_text("\n".join(["l"] * 200), encoding="utf-8")
    memory = tmp_path / "MEMORY.md"
    memory.write_text("l", encoding="utf-8")

    results = check_budgets(campaign, memory)
    ds = [r for r in results if r["target"] == "VAARN_DM_SCREEN.md"][0]
    assert ds["ok"] is False


def test_master_continuity_is_warn_only(tmp_path):
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    for f in ["WORLD_PROGRESS.md", "RESONANCE_INDEX.md", "VAARN_DM_SCREEN.md"]:
        (campaign / f).write_text("x", encoding="utf-8")
    (campaign / "MASTER_CONTINUITY_CURRENT.md").write_text("x" * 200000, encoding="utf-8")
    memory = tmp_path / "MEMORY.md"
    memory.write_text("l", encoding="utf-8")

    results = check_budgets(campaign, memory)
    mc = [r for r in results if r["target"] == "MASTER_CONTINUITY_CURRENT.md"][0]
    assert mc["ok"] is True  # warn-only never fails
    assert mc["warn"] is True


from hooks.session_verify import check_day_agreement


def test_day_agreement_pass():
    r = check_day_agreement(facts_day=129, current_status_day=129)
    assert r["ok"] is True


def test_day_disagreement_flags():
    r = check_day_agreement(facts_day=129, current_status_day=128)
    assert r["ok"] is False
    assert "129" in r["detail"] and "128" in r["detail"]


from hooks.session_verify import check_corrections_landed, check_cache_loop
from hooks.fabrication_bans import FabricationBans
from hooks.distillation_cache import DistillationCache


def test_correction_with_ban_and_cache_passes(tmp_path):
    bans = FabricationBans(tmp_path / "bans.json")
    bans.add_ban(entity="kael", wrong_terms=["botanist"],
                 correct_fact="Kael is a navigator.", failure_mode="rel",
                 session_id="s", turn=1)
    cache = DistillationCache(tmp_path / "cache.json")
    cache.put({"topic_key": "kael_identity", "learning": "Kael is a navigator.",
               "key_facts": ["navigator"], "source_pointers": [],
               "ingested_at_session": None})
    facts = {"corrections": [
        {"entity": "kael", "wrong_terms": ["botanist"], "topic_key": "kael_identity"}]}

    results = check_corrections_landed(facts, bans, cache)
    assert all(r["ok"] for r in results), results


def test_correction_missing_ban_flags(tmp_path):
    bans = FabricationBans(tmp_path / "bans.json")  # empty
    cache = DistillationCache(tmp_path / "cache.json")
    cache.put({"topic_key": "kael_identity", "learning": "x", "key_facts": [],
               "source_pointers": [], "ingested_at_session": None})
    facts = {"corrections": [
        {"entity": "kael", "wrong_terms": ["botanist"], "topic_key": "kael_identity"}]}

    results = check_corrections_landed(facts, bans, cache)
    assert any(not r["ok"] and "ban" in r["detail"] for r in results)


def test_correction_missing_cache_flags(tmp_path):
    bans = FabricationBans(tmp_path / "bans.json")
    bans.add_ban(entity="kael", wrong_terms=["botanist"],
                 correct_fact="Kael is a navigator.", failure_mode="rel",
                 session_id="s", turn=1)
    cache = DistillationCache(tmp_path / "cache.json")  # empty
    facts = {"corrections": [
        {"entity": "kael", "wrong_terms": ["botanist"], "topic_key": "kael_identity"}]}
    results = check_corrections_landed(facts, bans, cache)
    assert any(not r["ok"] and "cache fact" in r["detail"] for r in results)


def test_cache_loop_clean_when_no_unposted(tmp_path):
    cache = DistillationCache(tmp_path / "cache.json")
    cache.put({"topic_key": "k", "learning": "x", "key_facts": [],
               "source_pointers": [], "ingested_at_session": "s1"})
    r = check_cache_loop(cache)
    assert r["ok"] is True


def test_cache_loop_flags_unposted(tmp_path):
    cache = DistillationCache(tmp_path / "cache.json")
    cache.put({"topic_key": "k", "learning": "x", "key_facts": [],
               "source_pointers": [], "ingested_at_session": None})
    r = check_cache_loop(cache)
    assert r["ok"] is False
    assert "1" in r["detail"]


from hooks.session_verify import check_antagonist


def _make_dossier(dpath, name, status, log_day=None):
    text = f"# {name}\nStatus: {status}\n\n## Maintenance Log\n"
    if log_day is not None:
        text += f"- Day {log_day}: reviewed\n"
    (dpath / f"{name}_DOSSIER.md").write_text(text, encoding="utf-8")


def test_antagonist_passes_when_index_and_logs_current(tmp_path):
    campaign = tmp_path / "campaign"
    dossiers = campaign / "dossiers"
    dossiers.mkdir(parents=True)
    (campaign / "ANTAGONIST_DOSSIER_INDEX.md").write_text(
        "# Index\nLast updated: Day 129\n", encoding="utf-8")
    _make_dossier(dossiers, "SALISS", "ACTIVE", log_day=129)
    _make_dossier(dossiers, "TORVEN", "RIPENING", log_day=129)
    _make_dossier(dossiers, "OLDONE", "RESOLVED", log_day=80)  # resolved: not required

    r = check_antagonist(campaign, day=129)
    assert r["ok"] is True
    assert "1 active, 1 ripening" in r["detail"]


def test_antagonist_flags_missing_maintenance_log(tmp_path):
    campaign = tmp_path / "campaign"
    dossiers = campaign / "dossiers"
    dossiers.mkdir(parents=True)
    (campaign / "ANTAGONIST_DOSSIER_INDEX.md").write_text(
        "# Index\nLast updated: Day 129\n", encoding="utf-8")
    _make_dossier(dossiers, "SALISS", "ACTIVE", log_day=120)  # stale log

    r = check_antagonist(campaign, day=129)
    assert r["ok"] is False


def test_antagonist_flags_stale_index(tmp_path):
    campaign = tmp_path / "campaign"
    dossiers = campaign / "dossiers"
    dossiers.mkdir(parents=True)
    (campaign / "ANTAGONIST_DOSSIER_INDEX.md").write_text(
        "# Index\nLast updated: Day 120\n", encoding="utf-8")

    r = check_antagonist(campaign, day=129)
    assert r["ok"] is False
    assert "index" in r["detail"].lower()


def test_antagonist_no_dossiers_dir_is_ok(tmp_path):
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    r = check_antagonist(campaign, day=129)
    assert r["ok"] is True


from hooks.session_verify import compute_vital_signs


def test_vital_signs_clean(tmp_path):
    bans = FabricationBans(tmp_path / "bans.json")
    facts = {"corrections": [{"entity": "kael", "wrong_terms": ["botanist"]}],
             "narrative_log": "Vela read the journal by lamplight."}
    vs = compute_vital_signs(facts, bans, distillations_written=3)
    assert vs["corrections_captured"] == 1
    assert vs["banned_errors_in_prose"] == 0
    assert vs["distillations_written"] == 3
    assert vs["alarm"] is False


def test_vital_signs_alarm_when_banned_error_in_prose(tmp_path):
    bans = FabricationBans(tmp_path / "bans.json")
    bans.add_ban(entity="kael", wrong_terms=["botanist"],
                 correct_fact="Kael is a navigator.", failure_mode="rel",
                 session_id="s", turn=1)
    facts = {"corrections": [], "narrative_log": "Kael, the botanist, frowned."}
    vs = compute_vital_signs(facts, bans, distillations_written=0)
    assert vs["banned_errors_in_prose"] == 1
    assert vs["alarm"] is True


from hooks.session_verify import run_verification


def test_run_verification_pass1_aggregates(tmp_path):
    facts_path = _write_facts(tmp_path, corrections=[],
                              narrative_log="A quiet evening.")
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    memory = tmp_path / "MEMORY.md"
    for f in ["WORLD_PROGRESS.md", "RESONANCE_INDEX.md", "VAARN_DM_SCREEN.md",
              "MASTER_CONTINUITY_CURRENT.md"]:
        _touch_after(campaign / f, facts_path)
    # dm_narrative_synthesis.md lives in the memory dir, not the campaign dir.
    _touch_after(memory.parent / "dm_narrative_synthesis.md", facts_path)
    _touch_after(memory, facts_path)
    bans = FabricationBans(tmp_path / "bans.json")
    cache = DistillationCache(tmp_path / "cache.json")

    report = run_verification(facts_path, campaign, memory, bans, cache,
                              current_status_day=129, pass_number=1)
    assert report["overall_ok"] is True
    assert "checks" in report
    assert all(c["target"] != "cache_loop" for c in report["checks"])


def test_run_verification_pass2_includes_cache_and_vitals(tmp_path):
    facts_path = _write_facts(tmp_path, corrections=[], narrative_log="x")
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    memory = tmp_path / "MEMORY.md"
    for f in ["WORLD_PROGRESS.md", "RESONANCE_INDEX.md", "VAARN_DM_SCREEN.md",
              "MASTER_CONTINUITY_CURRENT.md"]:
        _touch_after(campaign / f, facts_path)
    # dm_narrative_synthesis.md lives in the memory dir, not the campaign dir.
    _touch_after(memory.parent / "dm_narrative_synthesis.md", facts_path)
    _touch_after(memory, facts_path)
    bans = FabricationBans(tmp_path / "bans.json")
    cache = DistillationCache(tmp_path / "cache.json")

    report = run_verification(facts_path, campaign, memory, bans, cache,
                              current_status_day=129, pass_number=2,
                              reindex_ok=True, distillations_written=2)
    assert any(c["target"] == "cache_loop" for c in report["checks"])
    assert report["vital_signs"]["distillations_written"] == 2
