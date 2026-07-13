"""Heartbeat Slice B — crossings. Engine co-locates tangles + forwards facts;
it judges NOTHING. All output is DM-facing RAG, invisible to the player."""
import json
import pytest
import server


@pytest.fixture
def xenv(tmp_path, monkeypatch):
    """Point the NPC / thread / faction stores at temp files and pin the
    campaign day. Each test fills the stores via the returned writers."""
    npc_file = tmp_path / "npc_states.json"
    thr_file = tmp_path / "narrative_threads.json"
    fac_file = tmp_path / "factions.json"

    def write_npcs(npcs):
        npc_file.write_text(json.dumps({"npcs": npcs, "meta": {}}), encoding="utf-8")

    def write_threads(threads):
        thr_file.write_text(
            json.dumps({"threads": threads, "resolved": {}, "meta": {}}),
            encoding="utf-8")

    def write_factions(factions):
        fac_file.write_text(json.dumps({"factions": factions, "meta": {}}), encoding="utf-8")

    # default: empty stores (cold start)
    write_npcs({})
    write_threads({})
    write_factions({})

    monkeypatch.setattr(server, "NPC_STATE_FILE", npc_file)
    monkeypatch.setattr(server, "THREADS_FILE", thr_file)
    monkeypatch.setattr(server, "FACTIONS_FILE", fac_file)
    monkeypatch.setattr(server, "_thread_current_day", lambda: 100)

    return type("XEnv", (), {
        "write_npcs": staticmethod(write_npcs),
        "write_threads": staticmethod(write_threads),
        "write_factions": staticmethod(write_factions),
    })


def _npc(name, **kw):
    rec = {"name": name, "disposition": kw.pop("disposition", "neutral")}
    rec.update(kw)
    return rec


def _clock(due_day=130, label="their plan", fired=False, fired_day=None):
    c = {"due_day": due_day, "label": label, "wound_day": 100, "pace": "cool", "fired": fired}
    if fired_day is not None:
        c["fired_day"] = fired_day
    return c


def _thread(title, desc="", clock=None, status="active", developments=None):
    return {
        "id": title.lower().replace(" ", "_"),
        "title": title,
        "description": desc,
        "introduced_day": 90,
        "urgency": "high",
        "foreshadowing": [],
        "developments": developments or [],
        "status": status,
        "clock": clock,
    }


# ---- liveness ----

def test_collect_empty_stores_returns_empty(xenv):
    # cold start: zero everything -> zero seeds, no error
    assert server._crossing_collect_seeds() == []


def test_collect_unfired_npc_clock_is_live(xenv):
    xenv.write_npcs({"vela": _npc("Vela", open_purpose="find the relay",
                                  purpose_clock=_clock())})
    seeds = server._crossing_collect_seeds()
    assert len(seeds) == 1
    s = seeds[0]
    assert s["kind"] == "npc" and s["id"] == "vela" and s["display"] == "Vela"
    assert s["label"] == "their plan" and s["persons"] == ["vela"]


def test_collect_fired_surfaced_npc_clock_is_dead(xenv):
    # fired AND surfaced (changed_while_away.surfaced True) -> not a live seed
    xenv.write_npcs({"vela": _npc(
        "Vela", purpose_clock=_clock(fired=True, fired_day=120),
        changed_while_away={"note": "x", "stamped_day": 120, "surfaced": True})})
    assert server._crossing_collect_seeds() == []


def test_collect_fired_unsurfaced_npc_clock_is_live(xenv):
    xenv.write_npcs({"vela": _npc(
        "Vela", purpose_clock=_clock(fired=True, fired_day=120),
        changed_while_away={"note": "x", "stamped_day": 120, "surfaced": False})})
    seeds = server._crossing_collect_seeds()
    assert len(seeds) == 1 and seeds[0]["fired"] is True


def test_collect_resolved_thread_is_dead(xenv):
    xenv.write_threads({"t": _thread("The Relay", clock=_clock(), status="resolved")})
    assert server._crossing_collect_seeds() == []


# ---- detection (group-by on strong tags) ----

def test_two_seeds_sharing_person_tangle(xenv):
    # an NPC purpose-clock on Vela + a thread that names Vela -> 1 person tangle
    xenv.write_npcs({"vela": _npc("Vela", purpose_clock=_clock(label="seize the relay"))})
    xenv.write_threads({"t": _thread("Sabotage", desc="Someone framed Vela for it.",
                                     clock=_clock(label="frame Vela"))})
    tangles = server._crossing_detect()
    assert len(tangles) == 1
    tg = tangles[0]
    assert tg["tag_type"] == "person" and tg["tag"] == "vela"
    assert tg["display"] == "Vela" and len(tg["seeds"]) == 2


def test_two_threads_share_faction_tangle(xenv):
    xenv.write_factions({"ferals": {"rep": -2, "opposed": []}})
    xenv.write_threads({
        "a": _thread("Raid", desc="The Ferals mass at the gate.", clock=_clock()),
        "b": _thread("Tribute", desc="Pay the Ferals or burn.", clock=_clock()),
    })
    tangles = server._crossing_detect()
    assert len(tangles) == 1
    assert tangles[0]["tag_type"] == "faction" and tangles[0]["tag"] == "ferals"


def test_shared_broad_place_alone_does_not_tangle(xenv):
    # two NPC seeds in the same location but NO shared person/faction -> NO tangle
    xenv.write_npcs({
        "vela": _npc("Vela", location="Ruin of Elenor", purpose_clock=_clock()),
        "orto": _npc("Orto", location="Ruin of Elenor", purpose_clock=_clock()),
    })
    assert server._crossing_detect() == []


def test_single_seed_is_not_a_tangle(xenv):
    xenv.write_npcs({"vela": _npc("Vela", purpose_clock=_clock())})
    assert server._crossing_detect() == []


def test_detect_empty_is_silent(xenv):
    assert server._crossing_detect() == []


# ---- fact-forwarding + render (engine forwards facts, judges nothing) ----

def test_facts_forward_disposition_no_verdict(xenv):
    xenv.write_npcs({"vela": _npc("Vela", disposition="hostile",
                                  purpose_clock=_clock(label="seize the relay"))})
    xenv.write_threads({"t": _thread("Frame", desc="Pin it on Vela.", clock=_clock())})
    tangle = server._crossing_detect()[0]
    facts = server._crossing_facts(tangle)
    joined = " ".join(facts).lower()
    assert "hostile" in joined and "vela" in joined
    # engine forwards FACTS, never a verdict
    for verdict in ("friction", "flashpoint", "allied", "opposed", "conflict"):
        assert verdict not in joined


def test_block_is_colocated_with_pull_handle(xenv):
    xenv.write_npcs({"vela": _npc("Vela", purpose_clock=_clock(label="seize the relay"))})
    xenv.write_threads({"t": _thread("Frame", desc="Pin it on Vela.", clock=_clock())})
    block = server._crossing_block(server._crossing_detect()[0])
    assert "Vela" in block
    assert "seize the relay" in block  # the npc seed label
    assert "search" in block           # a pull handle is offered


def test_distillation_handle_absent_when_no_distillations(xenv, monkeypatch, tmp_path):
    # cold start: no distillation cache file -> handle is None
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", tmp_path / "nope.json")
    xenv.write_npcs({"vela": _npc("Vela", purpose_clock=_clock())})
    xenv.write_threads({"t": _thread("Frame", desc="Pin it on Vela.", clock=_clock())})
    tangle = server._crossing_detect()[0]
    assert server._crossing_distillation_handle(tangle) is None


def test_distillation_handle_present_when_party_distilled(xenv, monkeypatch, tmp_path):
    cache = tmp_path / "distillations.json"
    cache.write_text(json.dumps({"distillations": {
        "vela_arc": {"learning": "x", "characters": ["Vela"], "entities": []}}}),
        encoding="utf-8")
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", cache)
    xenv.write_npcs({"vela": _npc("Vela", purpose_clock=_clock())})
    xenv.write_threads({"t": _thread("Frame", desc="Pin it on Vela.", clock=_clock())})
    tangle = server._crossing_detect()[0]
    assert server._crossing_distillation_handle(tangle) is not None


# ---- quiet channel: session-start briefing ----

def test_briefing_lines_one_per_tangle(xenv):
    xenv.write_npcs({"vela": _npc("Vela", purpose_clock=_clock(label="seize the relay"))})
    xenv.write_threads({"t": _thread("Frame", desc="Pin it on Vela.", clock=_clock(label="frame her"))})
    lines = server._crossing_briefing_lines()
    # exactly one tangle one-liner (the time-cluster needs >=2 SAME-DAY fired seeds)
    assert any("Vela" in ln for ln in lines)


def test_briefing_lines_empty_on_cold_start(xenv):
    assert server._crossing_briefing_lines() == []


# ---- §4 time-cluster: >=2 seeds fired in the same advance_day window ----

def test_time_cluster_two_same_day_fired_seeds(xenv):
    # two UNRELATED seeds (no shared person/faction) fired on the same day ->
    # one weak orientation line; NOT a person/faction tangle.
    xenv.write_npcs({
        "vela": _npc("Vela", purpose_clock=_clock(label="left town", fired=True, fired_day=95)),
        "orto": _npc("Orto", purpose_clock=_clock(label="changed sides", fired=True, fired_day=95)),
    })
    cluster = server._crossing_time_cluster_lines()
    assert len(cluster) == 1 and "95" in cluster[0]
    # and these unrelated seeds form no strong tangle
    assert server._crossing_detect() == []


def test_time_cluster_needs_two_same_day(xenv):
    # different fired_days -> no cluster
    xenv.write_npcs({
        "vela": _npc("Vela", purpose_clock=_clock(fired=True, fired_day=95)),
        "orto": _npc("Orto", purpose_clock=_clock(fired=True, fired_day=96)),
    })
    assert server._crossing_time_cluster_lines() == []


# ---- loud channel helper: blocks for a named NPC ----

def test_blocks_for_npc_returns_tangle_block(xenv):
    xenv.write_npcs({"vela": _npc("Vela", purpose_clock=_clock(label="seize the relay"))})
    xenv.write_threads({"t": _thread("Frame", desc="Pin it on Vela.", clock=_clock())})
    blocks = server._crossing_blocks_for_npc("vela")
    assert len(blocks) == 1 and "Vela" in blocks[0]


def test_blocks_for_uninvolved_npc_is_empty(xenv):
    xenv.write_npcs({"vela": _npc("Vela", purpose_clock=_clock())})
    # single seed -> no tangle -> no block, and an unrelated slug -> nothing
    assert server._crossing_blocks_for_npc("orto") == []


# ---- acceptance smoke (spec §10) ----

def test_zero_data_is_silent_no_errors(xenv):
    # cold start: every store empty -> no tangles, no briefing lines, no blocks
    assert server._crossing_collect_seeds() == []
    assert server._crossing_detect() == []
    assert server._crossing_briefing_lines() == []
    assert server._crossing_blocks_for_npc("anyone") == []


def test_loud_channel_surfaces_tangle_for_divergent_key_npc(xenv, tmp_path, monkeypatch):
    """Regression: check_canon's NPC injection must pass the ROSTER KEY (e.g.
    'varn look-home') to _crossing_blocks_for_npc, not npc.get('slug') or
    name.lower().  For titled NPCs the name.lower() doesn't match the roster
    key, so the bug caused the tangle block to be silently dropped.

    Pre-fix: _cx_slug = npc.get("slug") or name.lower()
             → "lord marshall varn look-home" ≠ "varn look-home" → no block.
    Post-fix: _cx_slug = npc_id  (the actual roster key) → match → block.
    """
    from dataclasses import dataclass
    from pathlib import Path

    # Seed: NPC with divergent key vs name (titled NPC)
    npc_key = "varn look-home"
    npc_name = "Lord Marshall Varn Look-Home"
    xenv.write_npcs({
        npc_key: _npc(npc_name, open_purpose="seize the relay",
                      purpose_clock=_clock(label="seize the relay")),
    })
    # Thread whose description names the NPC → forms a person tangle on npc_key
    xenv.write_threads({
        "relay_plot": _thread(
            "Relay Plot",
            desc=f"A plot against {npc_name}.",
            clock=_clock(label="counter the plot"),
        )
    })

    # Sanity-check at helper level: the tangle is detected and blocks surface
    blocks = server._crossing_blocks_for_npc(npc_key)
    assert len(blocks) == 1 and "Tangle" in blocks[0], (
        "Helper test failed — tangle not detected; check fixture setup")

    # Wire check_canon: point CAMPAIGN_DIR at tmp_path so it finds npc_states.json
    # (check_canon reads CAMPAIGN_DIR / "npc_states.json" directly)
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)

    # Provide the minimum files check_canon needs to not bail early
    lorebook_path = tmp_path / "lorebook.json"
    lorebook_path.write_text(json.dumps({"entries": []}), encoding="utf-8")

    @dataclass
    class _Ctx:
        pass

    output = server.check_canon(ctx=_Ctx(), user_input=f"I greet {npc_name}", needs=[])

    # The crossing block marker must appear in the output
    assert "\U0001f517" in output or "Tangle on" in output, (
        f"Expected crossing block in check_canon output for divergent-key NPC.\n"
        f"Got:\n{output[:800]}"
    )


def test_person_tangle_end_to_end_briefing(xenv):
    xenv.write_npcs({"vela": _npc("Vela", disposition="wary",
                                  purpose_clock=_clock(label="seize the relay"))})
    xenv.write_threads({"t": _thread("Frame Job", desc="Someone wants to frame Vela.",
                                     clock=_clock(label="frame Vela"))})
    lines = server._crossing_briefing_lines()
    assert len(lines) == 1
    assert "Vela" in lines[0] and "\U0001f517" in lines[0]
    # the loud block forwards the disposition fact, with no verdict
    block = server._crossing_blocks_for_npc("vela")[0].lower()
    assert "wary" in block
    for verdict in ("friction", "flashpoint", "opposed", "allied"):
        assert verdict not in block
