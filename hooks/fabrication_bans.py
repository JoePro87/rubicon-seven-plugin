"""The never-again list — a permanent store of banned canon claims.

One player correction = one ban. The Gate (validate_prose) hard-blocks any draft
that re-asserts a banned claim. Mirrors the blacklist.json pattern but for facts:
a fact only needs ONE correction to be banned (style needs several, facts do not).

A draft is flagged when a ban's entity name appears AND all of that ban's
distinctive wrong_terms appear in the draft (word-boundary, case-insensitive).
This stays narrow: a legitimate mention of the entity without the wrong terms is
never flagged.
"""

import json
import logging
import re
import time
from pathlib import Path

try:
    from hooks.hook_utils import file_lock
except ImportError:
    from hook_utils import file_lock


_SCHEMA_VERSION = 1


class FabricationBans:
    def __init__(self, path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _read(self):
        if not self.path.exists():
            return {"bans": [], "_meta": {"version": _SCHEMA_VERSION}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "bans" not in data:
                raise ValueError("malformed")
            return data
        except (json.JSONDecodeError, ValueError) as e:
            logging.warning(f"Fabrication ban list corrupted ({e}) — returning empty")
            return {"bans": [], "_meta": {"version": _SCHEMA_VERSION}}

    def _write(self, data):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            raise

    def all_bans(self):
        with file_lock(lock_path=self.lock_path, timeout=5):
            return list(self._read()["bans"])

    def add_ban(self, entity, wrong_terms, correct_fact, failure_mode, session_id, turn):
        entity = entity.strip().lower()
        terms = sorted({t.strip().lower() for t in wrong_terms if t.strip()})
        if not entity or not terms:
            return
        with file_lock(lock_path=self.lock_path, timeout=5):
            data = self._read()
            for b in data["bans"]:
                if b["entity"] == entity and sorted(b["wrong_terms"]) == terms:
                    return  # already banned
            data["bans"].append({
                "entity": entity,
                "wrong_terms": terms,
                "correct_fact": correct_fact,
                "failure_mode": failure_mode,
                "banned_session": session_id,
                "banned_turn": turn,
                "banned_at": time.strftime("%Y-%m-%d"),
            })
            data["_meta"]["version"] = data["_meta"].get("version", 0) + 1
            self._write(data)

    def check_draft(self, text):
        """Return the list of ban entries this draft violates."""
        low = text.lower()

        def present(token):
            return re.search(rf"\b{re.escape(token)}\b", low) is not None

        hits = []
        for b in self.all_bans():
            if present(b["entity"]) and all(present(t) for t in b["wrong_terms"]):
                hits.append(b)
        return hits
