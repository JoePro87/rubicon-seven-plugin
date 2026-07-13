"""XS fix wave (Fix 4): validate_prep_file gains two lint checks.

(a) WARN when a room has body text but none of its ### subsections match a
    recognized reveal-tier header (Observables/Obstacles/Loot/Secrets/DM
    Notes) -- legacy **Description:**-only or bare "### Area N:" formatting
    still loads (map_system._SECTION_TIER maps an unknown header -> 'obvious'
    by design), so this is advisory only, never a critical error.
(b) Lint prep-embedded tool-call strings against the LIVE registered tool
    list + known stale signatures: check_canon(...contexts=...) (now
    needs=), lookup_creature_stats(...) (retired; use
    lookup(action='creature')), and any name(action=...) naming a tool that
    is not currently registered.
"""
import server


def _write_prep(tmp_path, monkeypatch, content, filename="TEST_PREP.md"):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    (tmp_path / filename).write_text(content, encoding="utf-8")
    return filename


# ---------------------------------------------------------------------------
# (a) Reveal-tier subsection WARN
# ---------------------------------------------------------------------------

_NO_SUBSECTION_ROOM = """\
## ROOM: entrance
**Name:** The Entrance
**Floor:** 1
**Description:** A dusty hall with a single door east.
**Connections:** e->office
"""


def test_room_with_only_bold_description_warns(tmp_path, monkeypatch):
    fname = _write_prep(tmp_path, monkeypatch, _NO_SUBSECTION_ROOM)
    out = server.validate_prep_file(fname)
    assert "no recognized reveal-tier subsection" in out.lower()
    assert "entrance" in out.lower()


_LEGACY_AREA_ROOM = """\
## ROOM: vault
**Name:** The Vault
**Floor:** 1
**Connections:** n->entrance

### Area 1: The Vault Floor
Dust and old bones cover the floor.
"""


def test_room_with_legacy_area_header_warns(tmp_path, monkeypatch):
    fname = _write_prep(tmp_path, monkeypatch, _LEGACY_AREA_ROOM)
    out = server.validate_prep_file(fname)
    assert "no recognized reveal-tier subsection" in out.lower()
    assert "vault" in out.lower()


_RECOGNIZED_ROOM = """\
## ROOM: library
**Name:** The Library
**Floor:** 1
**Connections:** s->vault

### Observables
Shelves of rotted books line the walls.

### Secrets
A hidden lever behind the third shelf.
"""


def test_room_with_recognized_subsections_no_warn(tmp_path, monkeypatch):
    fname = _write_prep(tmp_path, monkeypatch, _RECOGNIZED_ROOM)
    out = server.validate_prep_file(fname)
    assert "no recognized reveal-tier subsection" not in out.lower()


_EMPTY_BODY_ROOM = """\
## ROOM: bare
"""


def test_bare_room_with_no_body_does_not_trigger_reveal_tier_warn(tmp_path, monkeypatch):
    """No body text at all -- the check requires body text to be present, so
    this is silent on THIS check (other schema warnings, e.g. missing
    **Name:**, are unrelated and may still fire)."""
    fname = _write_prep(tmp_path, monkeypatch, _EMPTY_BODY_ROOM)
    out = server.validate_prep_file(fname)
    assert "no recognized reveal-tier subsection" not in out.lower()


# ---------------------------------------------------------------------------
# (b) Stale tool-call lint
# ---------------------------------------------------------------------------

_STALE_CONTEXTS_PREP = """\
## ROOM: hall
**Name:** Hall
**Floor:** 1
**Connections:** n->exit

### Observables
DM note: call check_canon(needs="x", contexts="y") before revealing.
"""


def test_stale_check_canon_contexts_kwarg_warns(tmp_path, monkeypatch):
    fname = _write_prep(tmp_path, monkeypatch, _STALE_CONTEXTS_PREP)
    out = server.validate_prep_file(fname)
    assert "contexts=" in out and "needs=" in out.lower()


_STALE_LOOKUP_PREP = """\
## ROOM: hall
**Name:** Hall
**Floor:** 1
**Connections:** n->exit

### Observables
DM note: lookup_creature_stats("Iron Shepherd") for stats.
"""


def test_stale_lookup_creature_stats_warns(tmp_path, monkeypatch):
    fname = _write_prep(tmp_path, monkeypatch, _STALE_LOOKUP_PREP)
    out = server.validate_prep_file(fname)
    assert "lookup_creature_stats" in out and "retired" in out.lower()


_UNREGISTERED_TOOL_PREP = """\
## ROOM: hall
**Name:** Hall
**Floor:** 1
**Connections:** n->exit

### Observables
DM note: push totally_fake_tool(action="do_thing") here.
"""


def test_unregistered_action_call_warns(tmp_path, monkeypatch):
    fname = _write_prep(tmp_path, monkeypatch, _UNREGISTERED_TOOL_PREP)
    out = server.validate_prep_file(fname)
    assert "totally_fake_tool" in out
    assert "not a registered mcp tool" in out.lower()


_REGISTERED_TOOL_PREP = """\
## ROOM: hall
**Name:** Hall
**Floor:** 1
**Connections:** n->exit

### Observables
DM note: push npc(action="register") when this NPC is met.
"""


def test_registered_action_call_no_warn(tmp_path, monkeypatch):
    fname = _write_prep(tmp_path, monkeypatch, _REGISTERED_TOOL_PREP)
    out = server.validate_prep_file(fname)
    assert "not a registered mcp tool" not in out.lower()


# ---------------------------------------------------------------------------
# (c) Fog-map contract WARN (2026-07-05): rooms missing Floor/Connections
# ---------------------------------------------------------------------------

_MISSING_FLOOR_AND_CONNECTIONS_ROOM = """\
## ROOM: cellar
### Observables
Dust and bones.
"""


def test_room_missing_floor_and_connections_warns(tmp_path, monkeypatch):
    fname = _write_prep(tmp_path, monkeypatch, _MISSING_FLOOR_AND_CONNECTIONS_ROOM)
    out = server.validate_prep_file(fname)
    assert "cellar" in out and "**Floor:**" in out and "**Connections:**" in out
    assert "warn" in out.lower() or "⚠" in out


_HAS_FLOOR_AND_CONNECTIONS_ROOM = """\
## ROOM: cellar
**Floor:** 1
**Connections:** n->hall

### Observables
Dust and bones.
"""


def test_room_with_floor_and_connections_no_warn(tmp_path, monkeypatch):
    fname = _write_prep(tmp_path, monkeypatch, _HAS_FLOOR_AND_CONNECTIONS_ROOM)
    out = server.validate_prep_file(fname)
    assert "missing **Floor:**" not in out and "missing **Connections:**" not in out


_MISSING_FLOOR_ONLY_ROOM = """\
## ROOM: cellar
**Connections:** n->hall

### Observables
Dust and bones.
"""


def test_room_missing_floor_only_warns(tmp_path, monkeypatch):
    fname = _write_prep(tmp_path, monkeypatch, _MISSING_FLOOR_ONLY_ROOM)
    out = server.validate_prep_file(fname)
    assert "missing **Floor:**" in out
    assert "and **Connections:**" not in out
