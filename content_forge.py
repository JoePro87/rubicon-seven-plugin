"""Content Forge generation tools for Vaults of Vaarn."""

import json
import random
import logging
from pathlib import Path
from typing import Optional, Callable
from pydantic import Field
from tool_tags import TOOL_TAGS
import weapon_schema as _ws

logger = logging.getLogger("rubicon-seven.content-forge")


def _get_tool_tags(tool_name: str) -> set:
    return TOOL_TAGS.get(tool_name, set())


class ContentForge:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.tables = {}
        self.location_type_map = {}
        self._load_tables()

    def _load_tables(self):
        path = self.data_dir / "content_forge_tables.json"
        if not path.exists():
            logger.warning(f"Content forge tables not found: {path}")
            return
        with open(path, 'r') as f:
            data = json.load(f)
        raw = data.get("tables", {})
        self.location_type_map = raw.pop("_location_type_map", {})
        self.weather_chart = raw.pop("_weather_hex_chart", {})
        self.place_names = raw.pop("_region_place_names", {})
        self.tables = raw

    def _roll_die(self, die_str: str) -> int:
        size = int(die_str.lstrip('d'))
        return random.SystemRandom().randint(1, size)

    def _find_entry(self, table_name: str, roll: int):
        table = self.tables.get(table_name)
        if not table:
            return None
        for entry in table["entries"]:
            roll_val = entry["roll"]
            if isinstance(roll_val, str) and '-' in roll_val:
                parts = roll_val.split('-')
                try:
                    lo, hi = int(parts[0]), int(parts[1])
                    if lo <= roll <= hi:
                        return entry
                except ValueError:
                    continue
            else:
                try:
                    if int(roll_val) == roll:
                        return entry
                except (ValueError, TypeError):
                    continue
        return None

    def roll_on_table(self, table_name: str, specific_roll: Optional[int] = None) -> tuple:
        table = self.tables.get(table_name)
        if not table:
            return None, 0, f"Unknown table: {table_name}"
        die = table["die"]
        roll = specific_roll if specific_roll else self._roll_die(die)
        entry = self._find_entry(table_name, roll)
        if not entry:
            return None, roll, f"No entry for roll {roll} on {table_name} ({die})"
        return entry, roll, None


def chargen_weapon_obj(weapon_type: str, roll: Optional[int] = None) -> dict:
    """Return a structured weapon_schema object for a chargen weapon roll.

    weapon_type: 'melee' or 'ranged'
    roll: specific d20 roll (1-20); if None, rolls randomly.

    Field names from basic_weapon_melee / basic_weapon_ranged tables:
      Weapon, Damage, Slots, Tags  (melee)
      Weapon, Damage, Slots, Ammo, Tags  (ranged)
    """
    table_name = "basic_weapon_melee" if weapon_type == "melee" else "basic_weapon_ranged"
    data_dir = Path(__file__).parent / "data"
    forge = ContentForge(data_dir)
    entry, _, err = forge.roll_on_table(table_name, roll)
    if err:
        raise ValueError(f"chargen_weapon_obj error: {err}")
    f = entry["fields"]
    name = f.get("Weapon", "Unknown")
    damage = f.get("Damage", "d6")
    slots = int(f.get("Slots", 1))
    tags_str = f.get("Tags", "") or ""
    prose_tags = [t.strip() for t in tags_str.split(",") if t.strip()]
    ammo = f.get("Ammo") if weapon_type == "ranged" else None
    return _ws.build_weapon(
        name=name,
        damage=damage,
        slots=slots,
        prose_tags=prose_tags,
        range=weapon_type,
        ammo=ammo,
    )


def chargen_armour_obj(roll: Optional[int] = None) -> dict:
    """Return a structured weapon_schema armour object for a chargen body_armour roll.

    roll: specific d20 roll (1-20); if None, rolls randomly.

    Field names from body_armour table: Quality, Type, AV, Weight
    av_bonus = int(AV) - 10 (bonus over unarmoured AV 10).
    Slots parsed from Weight field (e.g. '3 Slots').
    Returns a _ws.build_armour() dict with display-only fields attached (_quality, _type, _av, _weight, _roll).
    """
    data_dir = Path(__file__).parent / "data"
    forge = ContentForge(data_dir)
    entry, actual_roll, err = forge.roll_on_table("body_armour", roll)
    if err:
        raise ValueError(f"chargen_armour_obj error: {err}")
    f = entry["fields"]
    quality = f.get("Quality", "")
    armour_type = f.get("Type", "Unknown")
    av_str = f.get("AV", "10")
    weight_str = f.get("Weight", "1 Slot")
    full_name = f"{quality} {armour_type}".strip() if quality else armour_type
    av_bonus = int(av_str) - 10
    try:
        slots = int(weight_str.split()[0])
    except (ValueError, IndexError):
        slots = 1
    obj = _ws.build_armour(name=full_name, av_bonus=av_bonus, slots=slots, prose_tags=[])
    # Attach display-only fields for the chargen renderer
    obj["_quality"] = quality
    obj["_type"] = armour_type
    obj["_av"] = av_str
    obj["_weight"] = weight_str
    obj["_roll"] = actual_roll
    return obj


def register_content_forge_tools(
    mcp,
    campaign_dir: Path,
    roll_encounter_fn: Optional[Callable] = None,
    roll_reaction_fn: Optional[Callable] = None,
    roll_exotica_fn: Optional[Callable] = None,
    roll_mutation_fn: Optional[Callable] = None,
    reaction_for_character_fn: Optional[Callable] = None,
    roll_check_fn: Optional[Callable] = None,
    roll_damage_fn: Optional[Callable] = None,
):
    data_dir = Path(__file__).parent / "data"
    forge = ContentForge(data_dir)

    LOCATION_SUBTABLES = [
        "anomaly", "archive", "arcology", "bandit_camp", "bounty_hunter",
        "cacklemaw_den", "faa_camp", "fortress", "grave", "hegemony_outpost",
        "holy_place", "oasis", "ruin", "science_mystic", "trade_post", "wreck",
        "hegemony_protectorate", "oracle_sanctum", "vault", "monster_lair", "settlement"
    ]

    def _roll_mutation(
        count: int = 1,
        specific_roll: Optional[int] = None,
    ) -> str:
        """Roll on the Cacogen Mutation Table (d100). DELEGATES to the single mutation
        mint path (roll_mutation_fn = generators._roll_cacogen_mutation); the forge only
        formats for display. Used for the mutation roll action + cacogen chargen."""
        if not roll_mutation_fn:
            return "Error: mutation roll not available"
        count = max(1, min(count, 4))
        results = []
        seen = set()
        attempts = 0
        while len(results) < count and attempts < 100:
            attempts += 1
            forced = specific_roll if (specific_roll and not results) else None
            m = roll_mutation_fn(forced) if forced else roll_mutation_fn()
            name = m.get("name", "Unknown")
            if name in seen and not forced:
                continue
            seen.add(name)
            roll_n = m.get("source", "d100=?").split("=")[-1]
            results.append(f"**{roll_n}. {name}** — {m.get('effect', 'No description')}")

        header = f"🧬 **Cacogen Mutation{'s' if count > 1 else ''}** (d100)"
        return f"{header}\n\n" + "\n\n".join(results)

    def _roll_location_subtable(
        location_type: str = "random",
        specific_roll: Optional[int] = None,
    ) -> str:
        """Roll on a location subtable (d20) for content generation. Each subtable provides multi-column details."""
        if location_type == "random":
            type_entry, type_roll, err = forge.roll_on_table("location_type")
            if err:
                return f"Error rolling location type: {err}"
            loc_name = type_entry["fields"].get("Location", "Unknown")
            subtable_key = forge.location_type_map.get(str(type_roll))
            result_header = f"**Location Type** (d20 → {type_roll}): **{loc_name}**\n\n"
            if subtable_key == "settlement":  # roll 2 is a Settlement — use the settlement generator
                return f"{result_header}{_roll_settlement()}"
            if not subtable_key or subtable_key not in forge.tables:
                return f"{result_header}No subtable available for this type. Use vault/encounter tools or content-forge skill."
        else:
            subtable_key = location_type.lower().replace(' ', '_').replace("'", "")
            result_header = ""
            if subtable_key == "settlement":
                return _roll_settlement()
            if subtable_key not in forge.tables:
                available = ", ".join(LOCATION_SUBTABLES)
                return f"Unknown location type: '{location_type}'\n\nAvailable: {available}"

        entry, roll, err = forge.roll_on_table(subtable_key, specific_roll)
        if err:
            return f"{result_header}Error: {err}"

        fields = entry.get("fields", {})
        display_name = subtable_key.replace('_', ' ').title()
        lines = [f"{result_header}📍 **{display_name}** (d20 → {roll})\n"]
        for k, v in fields.items():
            lines.append(f"- **{k}:** {v}")

        return "\n".join(lines)

    def _roll_soul() -> str:
        """Generate a complete location soul: etiology, history, temporal stakes, AI presence, and echoes.
        Use when designing a new vault, ruin, or significant location."""
        sections = []

        soul_tables = [
            ("etiology", "Origin (d20)"),
            ("history_layers", "History Layer (d12)"),
            ("temporal_stakes", "Temporal Stakes (d10)"),
            ("ancient_intelligences", "Ancient Intelligence (d8)"),
            ("ghosts_echoes", "Ghosts & Echoes (d8)"),
        ]

        for table_name, display_name in soul_tables:
            entry, roll, err = forge.roll_on_table(table_name)
            if err:
                sections.append(f"**{display_name}:** {err}")
                continue
            fields = entry.get("fields", {})
            parts = [f"{k}: {v}" for k, v in fields.items()]
            sections.append(f"**{display_name} [{roll}]:** {' | '.join(parts)}")

        # Roll a second history layer (locations have 2-3 layers)
        entry2, roll2, _ = forge.roll_on_table("history_layers")
        if entry2:
            fields2 = entry2.get("fields", {})
            parts2 = [f"{k}: {v}" for k, v in fields2.items()]
            sections.insert(2, f"**History Layer 2 (d12) [{roll2}]:** {' | '.join(parts2)}")

        return "🏛️ **LOCATION SOUL**\n\n" + "\n".join(sections)

    def _roll_settlement() -> str:
        """Generate a settlement profile from the certified Crimson Hound generators:
        government (adjective + form, with faith rolled SEPARATELY per the book note),
        values (praises / despises / lacks), a defining asset, and a current problem —
        each a d20 on the book tables. A light generative surface: roll, then weave the
        result into fiction; it is not a settlement simulation."""
        lines = ["🏘️ **SETTLEMENT** (Crimson Hound generators)\n"]

        gov, gr, gerr = forge.roll_on_table("settlement_government")
        faith, fr, ferr = forge.roll_on_table("settlement_government")  # roll separately for faith
        if gerr:
            lines.append(f"- **Government:** {gerr}")
        else:
            gf = gov["fields"]
            faith_val = faith["fields"]["Faith"] if not ferr else gf.get("Faith", "?")
            lines.append(f"- **Government [{gr}/{fr}]:** {gf['Adjective']} {gf['Form']} · Faith: {faith_val}")

        val, vr, verr = forge.roll_on_table("settlement_values")
        if not verr:
            vf = val["fields"]
            lines.append(f"- **Values [{vr}]:** praises *{vf['Praises']}* · despises *{vf['Despises']}* · lacks *{vf['Lacks']}*")

        asset, ar, aerr = forge.roll_on_table("settlement_asset")
        if not aerr:
            af = asset["fields"]
            lines.append(f"- **Asset [{ar}]:** {af['Asset']} — {af['Detail']}")

        prob, pr, perr = forge.roll_on_table("settlement_problem")
        if not perr:
            pf = prob["fields"]
            lines.append(f"- **Problem [{pr}]:** {pf['Problem']} — {pf['Detail']}")

        return "\n".join(lines)

    def _roll_landmark(specific_roll: Optional[int] = None) -> str:
        """Roll the certified d100 Landmarks table (VoV Referee's Toolbox p.177-178)."""
        entry, roll, err = forge.roll_on_table("landmarks", specific_roll)
        if err:
            return f"Landmark error: {err}"
        return f"🗺️ **Landmark** (d100 → {roll}): {entry['fields']['Landmark']}"

    def _roll_placename(category: str = "settlements") -> str:
        """Roll a certified region place-name (VoV Referee's Toolbox p.159-160).
        category: settlements|ruins|holy_places|hegemony_places|autarchic|mystic|faa_nomad.
        Partial book columns (e.g. faa_nomad) roll on their printed length."""
        cols = forge.place_names.get("columns", {})
        key = category.lower().replace(" ", "_").replace("-", "_")
        names = cols.get(key)
        if not names:
            return f"Unknown place-name category: '{category}'. Available: {', '.join(cols.keys())}"
        roll = forge._roll_die(f"d{len(names)}")
        return f"📛 **Place name** ({key}, d{len(names)} → {roll}): {names[roll - 1]}"

    # --- Weather hex-chart walk (VoV Referee's Toolbox pp.155-156) ---
    # Flat-top axial directions, r increases southward. d6: 1=NW 2=N 3=NE
    # 4=SE 5=S 6=SW (the chart's direction key). Off-chart moves wrap to
    # the opposite side of the chart along the movement axis; the ten
    # X-marked void cells block instead (the marker stays put that day).
    _WX_DIRS = {1: (-1, 0), 2: (0, -1), 3: (1, -1),
                4: (1, 0), 5: (0, 1), 6: (-1, 1)}

    WEATHER_STATE_FILE = campaign_dir / "weather_state.json"

    def _wx_on_chart(q: int, r: int) -> bool:
        return max(abs(q), abs(r), abs(q + r)) <= 3

    def _roll_weather(
        specific_roll: Optional[int] = None,
    ) -> str:
        """Walk the book's weather hex-chart: d6 direction once per desert day."""
        chart = forge.weather_chart
        if not chart:
            return "Weather error: _weather_hex_chart not loaded"
        by_label = {lbl: (c["q"], c["r"]) for lbl, c in chart["cells"].items()}
        by_coord = {v: k for k, v in by_label.items()}
        blocked = {tuple(c) for c in chart["blocked_void_cells"]}

        try:
            state = json.loads(WEATHER_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
        pos = state.get("position", chart["start"])
        if pos not in by_label:
            pos = chart["start"]

        if specific_roll is not None and specific_roll not in _WX_DIRS:
            return ("Weather error: specific_roll is a d6 DIRECTION "
                    "(1=NW 2=N 3=NE 4=SE 5=S 6=SW), got "
                    f"{specific_roll}")
        d6 = specific_roll if specific_roll in _WX_DIRS else forge._roll_die("d6")
        dir_name = chart["directions"][str(d6)]
        q, r = by_label[pos]
        dq, dr = _WX_DIRS[d6]
        tq, tr = q + dq, r + dr

        if _wx_on_chart(tq, tr):
            new_pos = by_coord[(tq, tr)]
            move_note = f"marker {pos} → {new_pos}"
        elif (tq, tr) in blocked:
            new_pos = pos
            move_note = f"edge marked X — marker stays put at {pos}"
        else:
            # Wrap: re-enter from the opposite side along the same axis.
            wq, wr = q, r
            while _wx_on_chart(wq - dq, wr - dr):
                wq, wr = wq - dq, wr - dr
            new_pos = by_coord[(wq, wr)]
            move_note = f"off the chart — wraps to the opposite side, marker {pos} → {new_pos}"

        weather = chart["cells"][new_pos]["weather"]
        effects = chart["effects"].get(weather, "")
        try:
            WEATHER_STATE_FILE.write_text(
                json.dumps({"position": new_pos, "weather": weather},
                           indent=2),
                encoding="utf-8")
        except Exception as e:
            logger.warning(f"weather state not saved: {e}")

        return (f"🌤️ **Weather** (d6 → {d6} {dir_name}; {move_note}): "
                f"**{weather}** [{new_pos}]\n{effects}")

    def _reset_weather() -> str:
        """Reset the weather marker to the chart's Start hex (new region / time skip)."""
        chart = forge.weather_chart
        if not chart:
            return "Weather error: _weather_hex_chart not loaded"
        start = chart["start"]
        weather = chart["cells"][start]["weather"]
        try:
            WEATHER_STATE_FILE.write_text(
                json.dumps({"position": start, "weather": weather}, indent=2),
                encoding="utf-8")
        except Exception as e:
            return f"Weather error: state not saved: {e}"
        return (f"🌤️ **Weather marker reset** to Start [{start}] — "
                f"current weather: **{weather}**. "
                'Roll daily via roll(action="weather").')

    def _roll_environment(
        table: str = "weather",
        specific_roll: Optional[int] = None,
    ) -> str:
        """Roll on environment tables for travel and exploration: weather or route hazards. Foraging redirects to the supply tool."""
        table_map = {
            "route_hazard": ("route_hazards", "Route Hazard"),
            "route_hazards": ("route_hazards", "Route Hazard"),
        }
        key = table.lower().replace(' ', '_')
        if key == "weather":
            return _roll_weather(specific_roll)
        if key == "weather_reset":
            return _reset_weather()
        if key == "foraging":
            return (
                "🌍 **Foraging moved to the survival engine.** The old forge table is retired; "
                "foraging now runs the certified rulebook d100 (S2, table-desert-foraging) with carried-ration "
                "credit and field-mode checks.\n"
                'NEXT: supply(action="forage", character="Name1,Name2") — comma-separated forager names, field mode only.'
            )
        if key not in table_map:
            return f"Unknown table: {table}. Available: weather, weather_reset, route_hazard, foraging (redirects to supply)"

        table_name, display = table_map[key]
        entry, roll, err = forge.roll_on_table(table_name, specific_roll)
        if err:
            return f"{display} error: {err}"

        fields = entry.get("fields", {})
        parts = [f"**{k}:** {v}" for k, v in fields.items()]
        die = forge.tables[table_name]["die"]
        return f"🌍 **{display}** ({die} → {roll})\n" + " | ".join(parts)

    def _roll_chargen(
        table: str = "full",
        mutation_count: int = 3,
    ) -> str:
        """Roll character generation tables. 'full' rolls weapon + armour + 2x gear + boon."""
        sections = []

        if table in ("weapon", "full"):
            # Crimson Hound chargen (rule-starting-equipment): the PC chooses a
            # melee OR a ranged weapon, then rolls d20 on that table. We roll both
            # and the PC keeps ONE. Tables are the verified book base-type tables.
            opts = []
            _, m_roll, m_err = forge.roll_on_table("basic_weapon_melee")
            if not m_err:
                mo = chargen_weapon_obj("melee", m_roll)
                m_tag = f", {', '.join(mo['tags'])}" if mo.get("tags") else ""
                opts.append(f"  - Melee (d20 → {m_roll}): {mo['name']} "
                            f"({mo['damage']}{m_tag}, {mo['slots']} slot)")
            _, r_roll, r_err = forge.roll_on_table("basic_weapon_ranged")
            if not r_err:
                ro = chargen_weapon_obj("ranged", r_roll)
                r_tag = f", {', '.join(ro['tags'])}" if ro.get("tags") else ""
                opts.append(f"  - Ranged (d20 → {r_roll}): {ro['name']} "
                            f"({ro['damage']}{r_tag}, {ro['slots']} slot, ammo {ro.get('ammo', '?')})")
            if opts:
                sections.append("**Weapon** — keep ONE (PC chooses melee or ranged):\n" + "\n".join(opts))

        if table in ("armour", "full"):
            # Body — mint through build_armour, render from object fields
            ao = chargen_armour_obj()
            sections.append(
                f"**Body Armour** (d20 → {ao['_roll']}): "
                f"{ao['_quality']} {ao['_type']} "
                f"(AV {ao['_av']}, {ao['_weight']})"
            )
            # Helm
            entry, roll, err = forge.roll_on_table("helm")
            if not err:
                f = entry["fields"]
                helm_name = f.get("Helm", "None")
                av_bonus = f.get("AV Bonus", "—")
                sections.append(f"**Helm** (d20 → {roll}): {helm_name} ({av_bonus})")
            # Shield
            entry, roll, err = forge.roll_on_table("shield")
            if not err:
                f = entry["fields"]
                shield_name = f.get("Shield", "None")
                av_bonus = f.get("AV Bonus", "—")
                sections.append(f"**Shield** (d20 → {roll}): {shield_name} ({av_bonus})")
            # NEXT CALL — armour only changes AV once it is WORN. After recording
            # the kept pieces to inventory (save_state inventory_changes, with the
            # body armour's av_bonus = AV − 10), wear each:
            #   character(action="equip", name="<pc>", item="<armour name>")
            # The engine then recomputes av.base = unarmoured + worn armour; never
            # hand-edit AV on the sheet.
            sections.append(
                "**→ Equip to apply AV:** record the kept pieces to inventory, then "
                "`character(action=\"equip\", name=\"<pc>\", item=\"<piece>\")` for each "
                "(body armour + any AV-bonus helm/shield). AV updates automatically; "
                "do not hand-edit the sheet.")

        if table in ("gear", "full"):
            for i in range(2 if table == "full" else 1):
                entry, roll, err = forge.roll_on_table("explorer_gear")
                if not err:
                    f = entry["fields"]
                    sections.append(f"**Gear {i+1}** (d20 → {roll}): {f.get('Item', '?')}")

        if table in ("boon", "full"):
            entry, roll, err = forge.roll_on_table("starting_boon")
            if not err:
                f = entry["fields"]
                sections.append(f"**Starting Boon** (d6 → {roll}): {f.get('Boon', '?')}")

        if table == "mutation" and roll_mutation_fn:
            mutation_count = max(1, min(mutation_count, 4))
            seen = set()
            attempts = 0
            i = 0
            while i < mutation_count and attempts < 100:
                attempts += 1
                m = roll_mutation_fn()
                name = m.get("name", "?")
                if name in seen:
                    continue
                seen.add(name)
                i += 1
                roll_n = m.get("source", "d100=?").split("=")[-1]
                sections.append(f"**Mutation {i}** (d100 → {roll_n}): {name} — {m.get('effect', '')}")

        if not sections:
            return f"Unknown table: {table}. Available: weapon, armour, gear, boon, mutation, full"

        header = "🎲 **CHARACTER GENERATION**\n" if table == "full" else f"🎲 **{table.upper()}**\n"
        return header + "\n".join(sections)

    def _list_forge_tables() -> str:
        """List all available content forge tables and their dice types."""
        lines = ["📋 **Content Forge Tables**\n"]
        categories = {
            "Soul Generation": ["etiology", "history_layers", "temporal_stakes", "ancient_intelligences", "ghosts_echoes"],
            "Location Subtables": LOCATION_SUBTABLES,
            "Settlement": ["settlement_government", "settlement_values", "settlement_despises", "settlement_lacks"],
            "Environment": ["route_hazards"],
            "Character Generation": ["basic_weapon_melee", "basic_weapon_ranged", "body_armour", "helm", "shield", "explorer_gear", "starting_boon"],
            "Reference": ["location_type"],
        }
        for cat, table_names in categories.items():
            lines.append(f"\n**{cat}:**")
            if cat == "Environment":
                n = len(forge.weather_chart.get("cells", {}))
                lines.append(f"  - weather (hex-chart walk, {n} cells, d6/day — "
                             "book pp.155-156; weather_reset re-centres the marker)")
            for name in table_names:
                table = forge.tables.get(name)
                if table:
                    lines.append(f"  - {name} ({table['die']}, {len(table['entries'])} entries)")
                else:
                    lines.append(f"  - {name} (not loaded)")
        return "\n".join(lines)

    # Dispatch table for the consolidated roll tool
    ROLL_DISPATCH = {
        "encounter": lambda **kw: roll_encounter_fn(
            table_name=kw.get("table_name", "Featureless Sands"),
            difficulty=kw.get("difficulty", "standard"),
            party_ego=kw.get("party_ego", 0),
        ) if roll_encounter_fn else "Error: encounter roll not available",
        "reaction": lambda **kw: (
            reaction_for_character_fn(
                character=kw["character"],
                can_communicate=kw.get("can_communicate", True),
                vs_ancestry=kw.get("vs_ancestry"),
                vs_faction=kw.get("vs_faction"),
                character_ego=kw.get("character_ego", 0),
            ) if (kw.get("character") and reaction_for_character_fn)
            else roll_reaction_fn(
                character_ego=kw.get("character_ego", 0),
                can_communicate=kw.get("can_communicate", True),
            )
        ) if roll_reaction_fn else "Error: reaction roll not available",
        "exotica": lambda **kw: roll_exotica_fn(
            specific_roll=kw.get("specific_roll", None),
        ) if roll_exotica_fn else "Error: exotica roll not available",
        "mutation": lambda **kw: _roll_mutation(
            count=kw.get("count", 1),
            specific_roll=kw.get("specific_roll", None),
        ),
        "location": lambda **kw: _roll_location_subtable(
            location_type=kw.get("location_type", "random"),
            specific_roll=kw.get("specific_roll", None),
        ),
        "soul": lambda **kw: _roll_soul(),
        "settlement": lambda **kw: _roll_settlement(),
        "landmark": lambda **kw: _roll_landmark(
            specific_roll=kw.get("specific_roll", None),
        ),
        "placename": lambda **kw: _roll_placename(
            category=kw.get("category", "settlements"),
        ),
        "weather": lambda **kw: _roll_weather(
            specific_roll=kw.get("specific_roll", None),
        ),
        "environment": lambda **kw: _roll_environment(
            table=kw.get("table", "weather"),
            specific_roll=kw.get("specific_roll", None),
        ),
        "chargen": lambda **kw: _roll_chargen(
            table=kw.get("table", "full"),
            mutation_count=kw.get("mutation_count", 3),
        ),
        "check": lambda **kw: roll_check_fn(
            kind="check", ability=kw.get("ability"), character=kw.get("character"),
            dc=kw.get("dc", 15), bonus=kw.get("bonus"),
            advantage=kw.get("advantage", False), disadvantage=kw.get("disadvantage", False),
            reason=kw.get("reason"),
        ) if roll_check_fn else "Error: ability check not available",
        "save": lambda **kw: roll_check_fn(
            kind="save", ability=kw.get("ability"), character=kw.get("character"),
            dc=kw.get("dc", 15), bonus=kw.get("bonus"),
            advantage=kw.get("advantage", False), disadvantage=kw.get("disadvantage", False),
            reason=kw.get("reason"),
        ) if roll_check_fn else "Error: save not available",
        "damage": lambda **kw: roll_damage_fn(
            notation=kw.get("notation"), reason=kw.get("reason"),
        ) if roll_damage_fn else "Error: damage roll not available",
        "list_tables": lambda **kw: _list_forge_tables(),
    }

    @mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": False},
        tags=_get_tool_tags("roll")
    )
    def roll(
        action: str = Field(description="encounter|reaction|exotica|mutation|location|soul|settlement|landmark|placename|weather|environment|chargen|check|save|damage|list_tables"),
        table_name: str = Field(default="Featureless Sands", description="[encounter] Encounter table name"),
        difficulty: str = Field(default="standard", description="[encounter] easy (d6), standard (d12), hard (d20)"),
        party_ego: int = Field(default=0, description="[encounter] Highest party EGO bonus"),
        character_ego: int = Field(default=0, description="[reaction] Highest PC EGO bonus if can communicate (ignored when 'character' is given — EGO read from the sheet)"),
        can_communicate: bool = Field(default=True, description="[reaction] Can party communicate with creature?"),
        character: Optional[str] = Field(default=None, description="[reaction] Named PC; reads EGO + traits from the sheet. [check/save] Named PC whose ability modifier is read from the sheet (with ability=)."),
        vs_ancestry: Optional[str] = Field(default=None, description="[reaction] Ancestry/species of the creature being met (e.g. 'true-kin') — drives ancestry-conditional ADV/DIS"),
        vs_faction: Optional[str] = Field(default=None, description="[reaction] Faction slug of the creature being met — Liked band = ADV, Disliked = DIS"),
        specific_roll: Optional[int] = Field(default=None, description="[exotica/mutation/location/weather/environment] Specific roll value, omit for random"),
        count: int = Field(default=1, description="[mutation] Number of mutations (1-4)"),
        location_type: str = Field(default="random", description="[location] Location type or 'random'"),
        category: str = Field(default="settlements", description="[placename] settlements|ruins|holy_places|hegemony_places|autarchic|mystic|faa_nomad"),
        table: str = Field(default="full", description="[chargen] weapon|armour|gear|boon|mutation|full. [environment] weather|route_hazard (foraging redirects to supply(action=\"forage\"))"),
        mutation_count: int = Field(default=3, description="[chargen] Mutations if rolling cacogen (1-4)"),
        ability: Optional[str] = Field(default=None, description="[check/save] Ability whose modifier applies — STR|DEX|CON|INT|PSY|EGO. Read from character='s sheet."),
        dc: int = Field(default=15, description="[check/save] Difficulty to beat (Vaarn standard = 15)."),
        bonus: Optional[int] = Field(default=None, description="[check/save] Flat modifier instead of a sheet ability (e.g. an NPC or a non-ability roll)."),
        advantage: bool = Field(default=False, description="[check/save] Roll 2d20, keep the higher."),
        disadvantage: bool = Field(default=False, description="[check/save] Roll 2d20, keep the lower."),
        notation: Optional[str] = Field(default=None, description="[damage] Dice expression to roll, e.g. '3d8' or '2d6+1' (HP costs, damage, spirit rolls)."),
        reason: Optional[str] = Field(default=None, description="[check/save/damage] Short label for what this roll is (shown in the result)."),
    ) -> str:
        """Reach for this WHEN you need a book-table roll — encounter, reaction, weather, chargen, mutation, exotica, or any random-table result during prep or play.

        encounter: Roll encounter table | reaction: NPC reaction | exotica: Random exotica | mutation: Cacogen mutation | location: Location subtable | soul: Location soul | settlement: Settlement profile | weather: Weather | environment: Environment subtable | chargen: Starting equipment | check/save: d20+ability vs DC (Vaarn standard 15; ability= off character='s sheet or bonus=, advantage/disadvantage, nat 20/1 auto) — the engine-attributed path for a player's own save/check | damage: roll a dice expr (notation='3d8') for HP costs/damage/spirit | list_tables: Show forge tables"""
        action = action.lower().strip()
        handler = ROLL_DISPATCH.get(action)
        if not handler:
            valid = ", ".join(sorted(ROLL_DISPATCH.keys()))
            return f"Invalid action: '{action}'. Valid actions: {valid}"
        return handler(
            table_name=table_name,
            difficulty=difficulty,
            party_ego=party_ego,
            character_ego=character_ego,
            can_communicate=can_communicate,
            character=character,
            vs_ancestry=vs_ancestry,
            vs_faction=vs_faction,
            specific_roll=specific_roll,
            count=count,
            location_type=location_type,
            table=table,
            mutation_count=mutation_count,
            ability=ability,
            dc=dc,
            bonus=bonus,
            advantage=advantage,
            disadvantage=disadvantage,
            notation=notation,
            reason=reason,
        )

    return forge
