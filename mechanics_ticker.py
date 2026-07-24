"""Mechanics Ticker — engine-authored, player-relay lines for state changes.

Iron Law 6 (amended 2026-07-20): mechanics numbers stay OUT of literary prose
and NPC dialogue, but every mechanical state change IS relayed to the player in
a marked, out-of-fiction block the DM reproduces verbatim after the prose. This
module is the deterministic source of that block; the damage / heal / condition
/ disease tools append it to the string they return.

WHO SEES WHAT:
- PC state carries EXACT numbers (the player owns their own sheet).
- ENEMY state is QUALITATIVE ONLY (unharmed/hurt/bloodied/down) — exact enemy
  HP and ability scores are DM-only, preserving threat mystery.

Leaf module: never imports server. Storage: <campaign>/mechanics_events.json,
a rolling list capped at 20, atomic writes via engine_core. Fail-open: any
exception inside record_events is swallowed — a persistence failure must never
crash a damage tool nor drop the ticker line the DM still needs to relay.
Spec: docs/superpowers/specs/2026-07-20-expedition-docket-mechanics-ticker.md
"""
import json
from pathlib import Path

from engine_core import _atomic_replace_with_retry

TICKER_HEADER = ">> MECHANICS (relay to player verbatim, after your prose):"
EVENTS_FILENAME = "mechanics_events.json"
_EVENTS_CAP = 20
LAST_EVENTS_DEFAULT = 5


# --- Rendering ---------------------------------------------------------------

def _enemy_word(pct) -> str:
    """Qualitative enemy-health word. Thresholds (spec B1):
    >= 1.0 unharmed · > 0.5 hurt · > 0 bloodied · <= 0 down.
    Non-numeric pct fails safe to 'hurt' (something landed)."""
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return "hurt"
    if p >= 1.0:
        return "unharmed"
    if p > 0.5:
        return "hurt"
    if p > 0:
        return "bloodied"
    return "down"


def _format_event(e: dict):
    """One event dict -> one relay line (no indent), or None if unknown kind."""
    kind = e.get("kind")
    name = e.get("name", "?")
    if kind == "pc_damage":
        dtype = e.get("dtype")
        dt = f" ({dtype})" if dtype else ""
        return (f"{name}: -{e.get('amount')} HP{dt} -> "
                f"{e.get('new_hp')}/{e.get('hp_max')}")
    if kind == "pc_heal":
        return f"{name}: +{e.get('amount')} HP -> {e.get('new_hp')}/{e.get('hp_max')}"
    if kind == "enemy_damage":
        return f"{name}: {_enemy_word(e.get('pct'))}"
    if kind == "enemy_ability":
        stat = e.get("stat")
        return f"{name}: weakened ({stat})" if stat else f"{name}: weakened"
    if kind == "condition":
        verb = "gained" if e.get("applied") else "cleared"
        return f"{name}: CONDITION {verb} - {e.get('condition')}"
    if kind == "wound":
        return f"{name}: WOUND - {e.get('wound')}"
    if kind == "ability_damage":
        return f"{name}: -{e.get('amount')} {e.get('stat')} -> {e.get('new_score')}"
    return None


def ticker_line(events) -> str:
    """Render the marked relay block for a list of event dicts.

    Empty / all-unknown events -> "" (no header, nothing to relay). ASCII-safe
    by construction: only "->", digits, and the event text (event authors keep
    names ASCII)."""
    if not events:
        return ""
    lines = [ln for ln in (_format_event(e) for e in events) if ln]
    if not lines:
        return ""
    return "\n".join([TICKER_HEADER] + [f"   {ln}" for ln in lines])


# --- Persistence (rolling ledger; fail-open) ---------------------------------

def _events_path(campaign_dir) -> Path:
    return Path(campaign_dir) / EVENTS_FILENAME


def _load_events(campaign_dir) -> dict:
    try:
        data = json.loads(_events_path(campaign_dir).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("events"), list):
            return data
    except Exception:
        pass
    return {"version": 1, "events": []}


def _current_day(campaign_dir):
    """Cheap read of the campaign day from characters/_meta.json (None if
    unavailable). 'bell' has no home in the state files, so it is omitted."""
    try:
        meta = json.loads(
            (Path(campaign_dir) / "characters" / "_meta.json").read_text(encoding="utf-8"))
        return meta.get("campaign_day")
    except Exception:
        return None


def record_events(campaign_dir, events) -> None:
    """Append events to mechanics_events.json (rolling, cap 20). Each stored
    event gets the current campaign day stamped when available. FAIL-OPEN: any
    exception is swallowed so a persistence hiccup never crashes a damage tool
    nor blocks the ticker line the caller already built."""
    if not events or campaign_dir is None:
        return
    try:
        ledger = _load_events(campaign_dir)
        day = _current_day(campaign_dir)
        for e in events:
            rec = dict(e)
            if day is not None and "day" not in rec:
                rec["day"] = day
            # Enemy events are QUALITATIVE at rest too: the stored ledger feeds
            # player_view (a player-facing surface), so the exact HP fraction
            # must not persist — quantize pct to the word and drop the number.
            if rec.get("kind") == "enemy_damage" and "pct" in rec:
                rec["state"] = _enemy_word(rec.pop("pct"))
            ledger["events"].append(rec)
        ledger["events"] = ledger["events"][-_EVENTS_CAP:]
        path = _events_path(campaign_dir)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(ledger, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        _atomic_replace_with_retry(tmp, path)
    except Exception:
        pass


def last_events(campaign_dir, n: int = LAST_EVENTS_DEFAULT) -> list:
    """The most recent n stored events (newest last), [] when the file is
    absent or unreadable. The player-view surface reads this."""
    return _load_events(campaign_dir).get("events", [])[-n:]


# --- The single seam callers use ---------------------------------------------

def append_ticker(text: str, events, campaign_dir=None) -> str:
    """Append the relay block to a tool's return string and persist the events.

    Non-empty events -> `text + "\\n\\n" + ticker_line(events)` (and record).
    Empty events -> text unchanged. campaign_dir defaults to the live campaign
    dir (engine_core.CAMPAIGN_DIR); tests pass an explicit dir."""
    if not events:
        return text
    if campaign_dir is None:
        try:
            from engine_core import CAMPAIGN_DIR
            campaign_dir = CAMPAIGN_DIR
        except Exception:
            campaign_dir = None
    record_events(campaign_dir, events)
    block = ticker_line(events)
    return f"{text}\n\n{block}" if block else text
