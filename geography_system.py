# ============================================
# RUBICON SEVEN - OVERWORLD GEOGRAPHY SYSTEM
# ============================================
#
# Player tool for tracking Vaarn geography:
# - Hex-based coordinate system (1 hex = 1 day foot travel)
# - ASCII overworld map rendering
# - Distance/route calculations
# - Prepped vs explored location tracking
#
# Prepped = Location exists in a module/prep file (appears on map)
# Explored = the party has physically been there
# Unmapped = No prep file exists (blank space)
#

import json
import math
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime

from tool_tags import TOOL_TAGS, Safety
from engine_core import read_rules_data

import random as _random


def _roll_dice(n, sides):
    """Return a list of n die rolls. Patchable in tests."""
    return [_random.randint(1, sides) for _ in range(n)]


class GeographySystem:
    """Overworld geography tracking for Vaarn hexcrawl campaigns."""

    def __init__(self, campaign_dir: Path):
        self.campaign_dir = campaign_dir
        self.geography_file = campaign_dir / "VAARN_GEOGRAPHY.json"
        self.map_file = campaign_dir / "OVERWORLD_MAP.md"
        self.on_depart = None
        self.on_arrive = None
        self.on_day_tick = None
        self.on_weather = None
        self.on_forced_march = None

    # ========================================
    # DATA MANAGEMENT
    # ========================================

    def _load_geography(self) -> Dict:
        """Load geography data from JSON file."""
        if not self.geography_file.exists():
            return self._create_default_geography()
        with open(self.geography_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _save_geography(self, data: Dict) -> None:
        """Save geography data to JSON file."""
        data["meta"]["last_updated"] = datetime.now().strftime("Day %d (updated %Y-%m-%d)")
        with open(self.geography_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def _create_default_geography(self) -> Dict:
        """Create default geography structure."""
        return {
            "meta": {
                "origin": "ceruline",
                "scale": "1 hex = 1 day foot travel (~15 miles)",
                "coordinate_system": "hex grid, N=+Y, E=+X, Ceruline at (0,0)",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "description": "Overworld geography for Vaarn campaign"
            },
            "locations": {},
            "regions": {},
            "routes": {}
        }

    # ========================================
    # LOCATION MANAGEMENT
    # ========================================

    def add_location(
        self,
        name: str,
        x: int,
        y: int,
        location_type: str,
        region: str,
        module: str = None,
        explored: bool = False,
        description: str = "",
        known: bool = False
    ) -> str:
        """Add a new location to the geography."""
        data = self._load_geography()

        # Normalize name to key
        key = name.lower().replace(" ", "_").replace("'", "")

        # Check for duplicate
        if key in data["locations"]:
            return f"Location '{name}' already exists. Use geography_update_location() to modify."

        # Check for coordinate collision
        for loc_key, loc in data["locations"].items():
            if loc["x"] == x and loc["y"] == y:
                return f"Coordinates ({x}, {y}) already occupied by '{loc_key}'"

        data["locations"][key] = {
            "x": x,
            "y": y,
            "type": location_type,
            "region": region,
            "module": module,
            "explored": explored,
            "known": known or explored,
            "description": description
        }

        self._save_geography(data)

        status = "EXPLORED" if explored else "PREPPED"
        return f"Added [{status}] {name} at ({x}, {y}) in {region}"

    def update_location(self, name: str, field: str, value: Any) -> str:
        """Update a field on an existing location."""
        data = self._load_geography()
        key = name.lower().replace(" ", "_").replace("'", "")

        if key not in data["locations"]:
            return f"Location '{name}' not found"

        valid_fields = ["x", "y", "type", "region", "module", "explored", "known", "description"]
        if field not in valid_fields:
            return f"Invalid field '{field}'. Valid: {', '.join(valid_fields)}"

        old_value = data["locations"][key].get(field)
        data["locations"][key][field] = value
        # Invariant: explored implies known (mirrors mark_explored).
        if field == "explored" and value:
            data["locations"][key]["known"] = True
        self._save_geography(data)

        return f"Updated {name}.{field}: {old_value} -> {value}"

    def mark_explored(self, name: str) -> str:
        """Mark a location as explored (the party has been there)."""
        data = self._load_geography()
        key = name.lower().replace(" ", "_").replace("'", "")

        if key not in data["locations"]:
            return f"Location '{name}' not found"

        if data["locations"][key]["explored"]:
            return f"'{name}' is already marked as explored"

        data["locations"][key]["explored"] = True
        data["locations"][key]["known"] = True
        self._save_geography(data)

        return f"Marked '{name}' as EXPLORED"

    def mark_known(self, name: str) -> str:
        """Mark a location as known-of by reputation (heard of, not yet visited)."""
        data = self._load_geography()
        key = name.lower().replace(" ", "_").replace("'", "")

        if key not in data["locations"]:
            return f"Location '{name}' not found"

        if data["locations"][key].get("known"):
            return f"'{name}' is already known"

        data["locations"][key]["known"] = True
        self._save_geography(data)

        return f"Marked '{name}' as KNOWN (known by reputation)"

    def _knowledge_state(self, loc: Dict) -> str:
        """Knowledge tier for a location, for fog-of-war surfacing:
          'full'   — explored (party has been there; full detail).
          'known'  — known-of by reputation (the macro chart: name/region/
                     direction/coords, but no interior).
          'fogged' — no knowledge (silent in unprompted injection).
        `explored` implies `known`.
        """
        if loc.get("explored"):
            return "full"
        if loc.get("known"):
            return "known"
        return "fogged"

    def remove_location(self, name: str) -> str:
        """Remove a location from geography."""
        data = self._load_geography()
        key = name.lower().replace(" ", "_").replace("'", "")

        if key not in data["locations"]:
            return f"Location '{name}' not found"

        # Also remove any routes involving this location
        routes_to_remove = [
            rkey for rkey, route in data["routes"].items()
            if route["from"] == key or route["to"] == key
        ]
        for rkey in routes_to_remove:
            del data["routes"][rkey]

        del data["locations"][key]
        self._save_geography(data)

        removed_routes = f" (also removed {len(routes_to_remove)} routes)" if routes_to_remove else ""
        return f"Removed location '{name}'{removed_routes}"

    # ========================================
    # ROUTE MANAGEMENT
    # ========================================

    def add_route(
        self,
        from_loc: str,
        to_loc: str,
        days_foot: float,
        days_ornithopter: float = None,
        hazard_level: str = "moderate",
        notes: str = ""
    ) -> str:
        """Add or update a route between two locations."""
        data = self._load_geography()

        from_key = from_loc.lower().replace(" ", "_").replace("'", "")
        to_key = to_loc.lower().replace(" ", "_").replace("'", "")

        # Validate locations exist
        if from_key not in data["locations"]:
            return f"Origin location '{from_loc}' not found"
        if to_key not in data["locations"]:
            return f"Destination location '{to_loc}' not found"

        # Calculate hex distance from coordinates
        from_loc_data = data["locations"][from_key]
        to_loc_data = data["locations"][to_key]
        hexes = self._hex_distance(
            from_loc_data["x"], from_loc_data["y"],
            to_loc_data["x"], to_loc_data["y"]
        )

        route_key = f"{from_key}_to_{to_key}"

        data["routes"][route_key] = {
            "from": from_key,
            "to": to_key,
            "hexes": hexes,
            "days_foot": days_foot,
            "days_ornithopter": days_ornithopter,
            "hazard_level": hazard_level,
            "notes": notes
        }

        self._save_geography(data)

        return f"Route added: {from_loc} -> {to_loc} ({hexes} hexes, {days_foot} days foot)"

    # ========================================
    # DISTANCE CALCULATIONS
    # ========================================

    def _hex_distance(self, x1: int, y1: int, x2: int, y2: int) -> int:
        """Calculate hex distance between two points (using axial coordinates)."""
        # For offset hex grid, convert to cube coordinates
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        return max(dx, dy, abs(dx - dy))

    def get_distance(self, origin: str, destination: str) -> Dict:
        """Calculate distance between two locations."""
        data = self._load_geography()

        origin_key = origin.lower().replace(" ", "_").replace("'", "")
        dest_key = destination.lower().replace(" ", "_").replace("'", "")

        if origin_key not in data["locations"]:
            return {"error": f"Origin '{origin}' not found"}
        if dest_key not in data["locations"]:
            return {"error": f"Destination '{destination}' not found"}

        origin_loc = data["locations"][origin_key]
        dest_loc = data["locations"][dest_key]

        hexes = self._hex_distance(
            origin_loc["x"], origin_loc["y"],
            dest_loc["x"], dest_loc["y"]
        )

        # Check for direct route data
        route_key = f"{origin_key}_to_{dest_key}"
        reverse_key = f"{dest_key}_to_{origin_key}"
        route = data["routes"].get(route_key) or data["routes"].get(reverse_key)

        result = {
            "origin": origin,
            "destination": destination,
            "hexes": hexes,
            "estimated_days_foot": hexes,  # 1 hex = 1 day default
            "as_crow_flies_miles": hexes * 15  # ~15 miles per hex
        }

        if route:
            result["route_exists"] = True
            result["canonical_days_foot"] = route["days_foot"]
            if route.get("days_ornithopter"):
                result["canonical_days_ornithopter"] = route["days_ornithopter"]
            result["hazard_level"] = route["hazard_level"]
            if route.get("notes"):
                result["notes"] = route["notes"]
        else:
            result["route_exists"] = False
            result["note"] = "No canonical route. Use geography_add_route() to define travel times."

        return result

    # Default transport speeds (mph) used if TRANSPORT_SPEEDS.json absent
    _DEFAULT_SPEEDS = {"foot": 2.5, "ornithopter": 120.0, "crawler": 18.0}

    def _load_transport_speeds(self) -> dict:
        """Load the transport speed table: engine rules-data as the base, with an
        optional campaign-side TRANSPORT_SPEEDS.json merged over it (campaign wins
        per entry — campaign-specific modes are play-state and never ship with the
        engine). Tolerates absence of either file."""
        try:
            base = json.loads(read_rules_data("TRANSPORT_SPEEDS.json"))
        except Exception:
            base = {"transport_modes": {
                k: {"name": k, "base_speed_mph": v} for k, v in self._DEFAULT_SPEEDS.items()}}
        try:
            campaign_path = self.campaign_dir / "TRANSPORT_SPEEDS.json"
            if campaign_path.exists():
                override = json.loads(campaign_path.read_text(encoding="utf-8"))
                for key, val in override.items():
                    if isinstance(val, dict) and isinstance(base.get(key), dict):
                        base[key].update(val)
                    else:
                        base[key] = val
        except Exception:
            pass  # fail-open: a malformed campaign file must never break travel math
        return base

    @staticmethod
    def _format_hours(hours: float) -> str:
        if hours < 1:
            return f"{int(round(hours * 60))} minutes"
        if hours < 24:
            return f"{hours:.1f} hours"
        return f"{hours / 24:.1f} days"

    def journey(self, origin: str, destination: str, mode: str = None) -> str:
        """Travel plan between two locations. Single source of truth: reads the
        enriched route schema in VAARN_GEOGRAPHY.json + TRANSPORT_SPEEDS.json.

        Prefers verified canonical times; otherwise estimates from distance +
        transport speed; falls back to hex/day estimate.
        """
        dist = self.get_distance(origin, destination)
        if "error" in dist:
            return f"Error: {dist['error']}"

        data = self._load_geography()
        ok = origin.lower().replace(" ", "_").replace("'", "")
        dk = destination.lower().replace(" ", "_").replace("'", "")
        route = data["routes"].get(f"{ok}_to_{dk}") or data["routes"].get(f"{dk}_to_{ok}") or {}

        miles = route["distance_miles"] if route.get("distance_miles") is not None else dist["as_crow_flies_miles"]
        terrain = route.get("terrain", "unknown")
        speeds = self._load_transport_speeds().get("transport_modes", {})
        canonical = route.get("canonical_times", {})

        lines = [f"# Journey: {dist['origin']} → {dist['destination']}", "",
                 f"**Distance:** {miles:.0f} miles ({dist['hexes']} hexes)",
                 f"**Terrain:** {terrain}", ""]

        modes = [mode] if mode else (list(speeds.keys()) or ["foot", "ornithopter"])
        for mname in modes:
            c = canonical.get(mname, {})
            if c.get("time"):
                mark = "✓ verified" if c.get("verified") else "≈ recorded"
                lines.append(f"- **{mname}:** {c['time']} ({mark})")
                continue
            mdata = speeds.get(mname, {})
            speed = mdata.get("base_speed_mph") or self._DEFAULT_SPEEDS.get(mname, 0)
            if speed > 0:
                hours = miles / speed
                lines.append(f"- **{mname}:** {self._format_hours(hours)} (calculated @ {speed} mph)")
            else:
                lines.append(f"- **{mname}:** no data available (unknown transport mode)")
        if route.get("hazard_level"):
            lines.append("")
            lines.append(f"**Hazard:** {route['hazard_level']}")
        return "\n".join(lines)

    # ========================================
    # QUERY FUNCTIONS
    # ========================================

    def query_locations(
        self,
        region: str = None,
        center: str = None,
        radius: int = None,
        explored_only: bool = False,
        location_type: str = None
    ) -> List[Dict]:
        """Query locations by various criteria."""
        data = self._load_geography()
        results = []

        # Get center coords if specified
        center_x, center_y = 0, 0
        if center:
            center_key = center.lower().replace(" ", "_").replace("'", "")
            if center_key in data["locations"]:
                center_x = data["locations"][center_key]["x"]
                center_y = data["locations"][center_key]["y"]

        for key, loc in data["locations"].items():
            # Filter by region
            if region and loc["region"] != region:
                continue

            # Filter by explored status
            if explored_only and not loc["explored"]:
                continue

            # Filter by type
            if location_type and loc["type"] != location_type:
                continue

            # Filter by radius from center
            if radius is not None:
                dist = self._hex_distance(center_x, center_y, loc["x"], loc["y"])
                if dist > radius:
                    continue

            results.append({
                "name": key,
                "x": loc["x"],
                "y": loc["y"],
                "type": loc["type"],
                "region": loc["region"],
                "explored": loc["explored"],
                "known": loc.get("known", False),
                "module": loc.get("module"),
                "description": loc.get("description", "")
            })

        # Sort by distance from center if center specified
        if center:
            results.sort(key=lambda l: self._hex_distance(center_x, center_y, l["x"], l["y"]))
        else:
            results.sort(key=lambda l: (l["x"], l["y"]))

        return results

    def position_context(self, center: str, radius: int = 6) -> str:
        """Position-relative overworld summary from `center` with Phase 3 fog gate.
        Fogged locations (neither explored nor known) are silently dropped; locations
        known by reputation are tagged "(by repute)". Lists nearby locations with hex
        distance + hazard, nearest first. Empty string if center unknown.
        """
        data = self._load_geography()
        center_key = center.lower().replace(" ", "_").replace("'", "")
        if center_key not in data["locations"]:
            return ""

        nearby = self.query_locations(center=center_key, radius=radius)
        rows = []
        for loc in nearby:
            key_norm = loc.get("name", "")
            if not key_norm or key_norm == center_key:
                continue
            # Phase 3 fog: never surface a location the party has no knowledge of.
            state = self._knowledge_state(loc)
            if state == "fogged":
                continue
            dist = self.get_distance(center_key, key_norm)
            if "error" in dist:
                continue
            hazard = dist.get("hazard_level", "")
            hz = f", hazard {hazard}" if hazard else ""
            unit = "hex" if dist["hexes"] == 1 else "hexes"
            repute = " (by repute)" if state == "known" else ""
            rows.append((dist["hexes"],
                         f"- {key_norm} [{loc.get('type', '?')}]: {dist['hexes']} {unit}{hz}{repute}"))

        if not rows:
            return ""
        rows.sort(key=lambda r: r[0])
        shown = rows[:8]
        hidden = len(rows) - len(shown)
        overflow = f"\n(+{hidden} more within {radius} hexes)" if hidden else ""
        body = "\n".join(r[1] for r in shown)
        return f"**OVERWORLD — near {center_key}** (within {radius} hexes):\n{body}{overflow}"

    def list_regions(self) -> str:
        """List all defined regions with their characteristics."""
        data = self._load_geography()

        lines = ["VAARN REGIONS", "=" * 40, ""]

        for key, region in data.get("regions", {}).items():
            lines.append(f"**{key.upper().replace('_', ' ')}**")
            lines.append(f"  Terrain: {region.get('terrain', 'unknown')}")
            lines.append(f"  {region.get('description', '')}")
            if region.get("encounter_table"):
                lines.append(f"  Encounters: {region['encounter_table']}")
            lines.append("")

        return "\n".join(lines)

    def validate_consistency(self) -> str:
        """Spatial sanity check for dm-design / content-forge. Reports:
          - coordinate collisions (two locations on the same hex)
          - routes referencing a missing location
          - locations whose region is not defined in the regions map
        Returns a clean-bill string if none found.
        """
        data = self._load_geography()
        locations = data.get("locations", {})
        regions = data.get("regions", {})
        routes = data.get("routes", {})
        issues = []

        # Coordinate collisions
        seen = {}
        for key, loc in locations.items():
            coord = (loc.get("x"), loc.get("y"))
            if coord[0] is None or coord[1] is None:
                issues.append(f"- MISSING COORDS: '{key}' has no x/y coordinates")
                continue
            if coord in seen:
                issues.append(f"- COLLISION: '{key}' and '{seen[coord]}' both at ({coord[0]}, {coord[1]})")
            else:
                seen[coord] = key

        # Routes referencing a missing location
        for rkey, route in routes.items():
            for end in ("from", "to"):
                ref = route.get(end)
                if not ref:
                    issues.append(f"- MALFORMED ROUTE: '{rkey}' missing '{end}' field")
                elif ref not in locations:
                    issues.append(f"- DANGLING ROUTE: '{rkey}' references missing location '{ref}'")

        # Unknown regions
        for key, loc in locations.items():
            region = loc.get("region")
            if region and region not in regions:
                issues.append(f"- UNKNOWN REGION: '{key}' has region '{region}' not defined in regions map")

        if not issues:
            return (f"✅ Geography consistent — {len(locations)} locations, "
                    f"{len(routes)} routes, {len(regions)} regions, no issues.")
        return "⚠️ Geography consistency issues:\n" + "\n".join(issues)

    # ========================================
    # PARTY LOCATION TRACKING
    # ========================================

    def get_party_location(self) -> Optional[str]:
        """Get current party overworld location."""
        data = self._load_geography()
        return data["meta"].get("party_location", "ceruline")

    def set_party_location(self, location: str) -> str:
        """Set current party overworld location."""
        data = self._load_geography()

        location_key = location.lower().replace(" ", "_").replace("'", "")
        if location_key not in data["locations"]:
            return f"Location '{location}' not found in geography"

        old_location = data["meta"].get("party_location", "ceruline")
        data["meta"]["party_location"] = location_key
        self._save_geography(data)

        return f"Party location updated: {old_location} -> {location_key}"

    # ---- Travel state (atomic, mirrors weather_state.json) -------------------
    def _travel_state_path(self):
        return self.campaign_dir / "travel_state.json"

    def get_travel_state(self) -> dict:
        p = self._travel_state_path()
        if not p.exists():
            return {"active": False}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {"active": False}

    def _save_travel_state(self, state: dict):
        import os
        p = self._travel_state_path()
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, p)

    def _resolve_days(self, origin_key, dest_key, mode) -> float:
        """Travel days for the journey, mode-aware.

        Resolution order: (1) canonical per-mode route days (days_<mode>),
        (2) the transport-speed table's daily range for fast modes (an
        ornithopter covers ~960 mi/day — it must never be charged foot-days),
        (3) days_foot / dice band, with the legacy vehicle halving."""
        data = self._load_geography()
        route = (data["routes"].get(f"{origin_key}_to_{dest_key}")
                 or data["routes"].get(f"{dest_key}_to_{origin_key}") or {})
        per_mode = route.get(f"days_{mode}")
        if per_mode is not None:
            return float(per_mode)
        if mode not in ("foot", "vehicle"):
            mdata = self._load_transport_speeds().get("transport_modes", {}).get(mode)
            if isinstance(mdata, dict):
                daily = mdata.get("daily_range_miles") or (
                    (mdata.get("base_speed_mph") or 0)
                    * (mdata.get("sustained_hours") or 8))
                miles = route.get("distance_miles")
                if miles is None:
                    dist = self.get_distance(origin_key, dest_key)
                    miles = (dist.get("as_crow_flies_miles")
                             if isinstance(dist, dict) else None)
                if daily and miles:
                    import math
                    return float(max(1, math.ceil(miles / daily)))
        if route.get("days_foot") is not None:
            days = float(route["days_foot"])
        else:
            dist = self.get_distance(origin_key, dest_key)
            hexes = dist.get("hexes", 1) if isinstance(dist, dict) else 1
            n = 1 if hexes <= 2 else (2 if hexes <= 4 else 3)
            days = float(sum(_roll_dice(n, 6)))
        if mode == "vehicle":
            days = max(1.0, round(days / 2.0))
        return days

    def travel_depart(self, destination: str, mode: str = "foot", noisy: bool = False,
                      origin: str = None) -> str:
        data = self._load_geography()
        if origin:
            origin_key = origin.lower().replace(" ", "_").replace("'", "")
            if origin_key not in data["locations"]:
                return f"Error: origin '{origin}' not found in geography"
            # The explicit origin is the truth — persist it so the stored
            # party_location can't stay stale for the next depart.
            data["meta"]["party_location"] = origin_key
            self._save_geography(data)
        else:
            origin_key = data["meta"].get("party_location", "ceruline")
        dest_key = destination.lower().replace(" ", "_").replace("'", "")
        if dest_key not in data["locations"]:
            return f"Error: destination '{destination}' not found in geography"
        days = self._resolve_days(origin_key, dest_key, mode)
        state = {
            "active": True, "origin": origin_key, "destination": dest_key,
            "mode": mode, "days_total": days, "days_remaining": days,
            "pace": "normal", "noisy": bool(noisy), "log": [],
        }
        self._save_travel_state(state)
        origin_note = ("" if origin else
                       f"\nOrigin read from stored party location — if that's wrong, "
                       f"re-depart with origin=\"<place>\" to correct it.")
        return (f"▶ DEPART {origin_key} → {dest_key} — {days:g} days ({mode}).{origin_note}\n"
                f"Supply now FIELD mode (rations burn daily).\n"
                f"→ geography(action=\"travel_day\") to advance the first day.")

    def travel_arrive(self) -> str:
        state = self.get_travel_state()
        if not state.get("active"):
            return "No active journey to arrive from."
        dest = state["destination"]
        self.set_party_location(dest)
        self._save_travel_state({"active": False})
        out = (f"▶ ARRIVED at {dest} (journey complete).\n"
               f"→ IF this is a supplied base (settlement/earned camp): "
               f"supply(action=\"arrive\", location=\"{dest}\") to refill + stamp the return clock. "
               f"A ruin/vault/wilderness arrival is NOT a base — supply stays FIELD there.\n"
               f"→ if {dest} is an adventure site: map(action=\"enter_site\", map_name=\"{dest}\", "
               f"prep_file=\"{dest.upper()}_PREP.md\") to start its turn clock.")
        try:
            import site_features
            entry = site_features.place_entry(self.campaign_dir, dest)
            if entry and entry.get("features"):
                out += "\n" + site_features.format_features_block(entry)
        except Exception:
            pass  # fail-soft: a broken ledger never breaks arrival
        return out

    # Weather travel-effect map (book p.146).
    _WEATHER_TRAVEL = {
        "Still": "normal", "Hazy": "normal", "Heatwave": "normal",
        "Dust Storm": "half", "Worm-pollen": "half",
        "Sand Storm": "none", "Prismatic Tempest": "none", "Rain": "normal",
    }

    def _roll_weather(self) -> dict:
        """Current weather -> {name, travel}. Reads the on_weather callback if wired,
        else Still. Patched directly in tests."""
        if getattr(self, "on_weather", None):
            try:
                name = self.on_weather()
            except Exception:
                name = "Still"
        else:
            name = "Still"
        return {"name": name, "travel": self._WEATHER_TRAVEL.get(name, "normal")}

    def _encounter_die(self, dice_count) -> int:
        """Roll dice_count d6, take lowest (book: 2d6/3d6-lowest if slow/noisy)."""
        return min(_roll_dice(dice_count, 6))

    def travel_day(self, pace: str = "normal", forage: bool = False) -> str:
        state = self.get_travel_state()
        if not state.get("active"):
            return "No active journey. Use geography(action=\"depart\", destination=...) first."
        lines = []
        weather = self._roll_weather()
        travel_mode = weather["travel"]
        lines.append(f"Weather: {weather['name']}")
        if weather["name"] == "Heatwave":
            lines.append("⚠ Heatwave — PCs consume 2× water today.")
        if getattr(self, "on_day_tick", None):
            try:
                self.on_day_tick(double_water=(weather["name"] == "Heatwave"))
            except Exception:
                pass
        if forage:
            self._save_travel_state(state)
            return ("Forage day (no travel progress).\n→ supply(action=\"forage\", "
                    "character=\"<names>\") to roll the desert foraging table.\n"
                    "→ geography(action=\"travel_day\") to resume travelling.")
        dice_count = 1
        if state.get("noisy") or pace == "forced":
            dice_count = 2
        day_die = self._encounter_die(dice_count)
        night_die = self._encounter_die(dice_count)
        vig = _roll_dice(1, 6)[0]
        vig_note = (" (you spot it first)" if vig == 6 else
                    " (it spots you first)" if vig == 1 else "")
        encounter = None
        for label, die in (("day", day_die), ("night", night_die)):
            if die == 1:
                encounter = label
            elif die == 2:
                lines.append(f"{label.capitalize()}: Omen (a sign on the horizon).")
        if travel_mode == "none":
            lines.append(f"No travel possible in {weather['name']} — the party hunkers down.")
            if weather["name"] == "Prismatic Tempest":
                lines.append("⚠ Prismatic Tempest: 3d6 electrical damage per hour above ground.")
            step = 0.0
        elif travel_mode == "half":
            lines.append(f"{weather['name']} — half speed today.")
            step = 0.5
        else:
            step = 1.0
        if pace == "forced" and step > 0:
            step *= 2
            lines.append("Forced march: 2× distance — see Exhaustion.")
        state["days_remaining"] = round(max(0.0, state["days_remaining"] - step), 2)
        state["log"].append(f"d{day_die}/n{night_die} w:{weather['name']} -{step}")
        self._save_travel_state(state)
        # Forced-march Exhaustion (book p.142): fills a slot; all-full = death.
        if pace == "forced":
            lines.append("⚠ Exhaustion: the marching PC fills one inventory slot with "
                         "Exhaustion (cleared by a full camp day; all slots full = death).")
            if getattr(self, "on_forced_march", None):
                try:
                    self.on_forced_march()
                except Exception:
                    pass
        # Getting lost (book p.142): ONLY when sun/stars obscured (a no-travel
        # weather pushed through under a forced pace) -> +d6 days.
        if travel_mode == "none" and pace == "forced":
            lost = _roll_dice(1, 6)[0]
            state["days_remaining"] = round(state["days_remaining"] + lost, 2)
            self._save_travel_state(state)
            lines.append(f"⚠ Lost in the storm: +{lost} days to the journey.")
        if encounter:
            lines.append(f"⚠ ENCOUNTER ({encounter}){vig_note} — pausing travel.")
            lines.append("→ roll(action=\"encounter\", table_name=\"<local table>\") for what it is.")
            lines.append("→ roll(action=\"reaction\", character=\"<highest-EGO PC>\", "
                         "vs_ancestry=\"<if known>\") for its disposition.")
            lines.append("→ geography(action=\"travel_day\") to resume when resolved.")
            return "\n".join(lines)
        if state["days_remaining"] <= 0:
            lines.append("→ geography(action=\"arrive\") — you've reached your destination.")
        else:
            lines.append(f"{state['days_remaining']:g} days remaining. "
                         f"→ geography(action=\"travel_day\") for the next day.")
        return "\n".join(lines)

    # ========================================
    # CONTEXT INJECTION SUPPORT
    # ========================================

    def get_location_context(self, location_name: str) -> Optional[Dict]:
        """Get full context for a location including travel times from party."""
        data = self._load_geography()

        # Normalize location name
        location_key = location_name.lower().replace(" ", "_").replace("'", "")

        # Try to find matching location
        matched_key = None
        for key in data["locations"]:
            if location_key in key or key in location_key:
                matched_key = key
                break
            # Also check display name match
            display_name = key.replace("_", " ")
            if location_key in display_name or display_name in location_key:
                matched_key = key
                break

        if not matched_key:
            return None

        loc = data["locations"][matched_key]
        party_loc = data["meta"].get("party_location", "ceruline")

        context = {
            "name": matched_key.replace("_", " ").title(),
            "key": matched_key,
            "coordinates": f"({loc['x']}, {loc['y']})",
            "type": loc["type"],
            "region": loc["region"].replace("_", " ").title(),
            "explored": loc["explored"],
            "knowledge": self._knowledge_state(loc),
            "description": loc.get("description", "")
        }

        # Add travel info from party location
        if matched_key != party_loc:
            distance = self.get_distance(party_loc, matched_key)
            if "error" not in distance:
                context["from_party"] = {
                    "party_location": party_loc.replace("_", " ").title(),
                    "hexes": distance["hexes"],
                    "miles_approx": distance["as_crow_flies_miles"]
                }
                if distance.get("route_exists"):
                    context["from_party"]["days_foot"] = distance["canonical_days_foot"]
                    if distance.get("canonical_days_ornithopter"):
                        context["from_party"]["days_ornithopter"] = distance["canonical_days_ornithopter"]
                    context["from_party"]["hazard"] = distance["hazard_level"]
                else:
                    context["from_party"]["days_foot_estimate"] = distance["estimated_days_foot"]
        else:
            context["from_party"] = {"is_current_location": True}

        return context

    def scan_for_locations(self, text: str) -> List[Dict]:
        """Scan text for any mentioned locations and return their contexts."""
        data = self._load_geography()
        found = []
        text_lower = text.lower()
        text_nospace = text_lower.replace(" ", "")

        for key, loc in data["locations"].items():
            # Check key-based match (e.g., "salt_bones", "delta_complex")
            key_spaceless = key.replace("_", "")
            display_name = key.replace("_", " ")

            # Split key into parts for partial matching (e.g., "midden" matches "midden_oracle")
            key_parts = key.split("_")

            # Match on various forms
            matched = False

            # Exact key match
            if key in text_lower or display_name in text_lower:
                matched = True
            # Spaceless match
            elif key_spaceless in text_nospace:
                matched = True
            # Partial match: any significant part of the name (3+ chars)
            else:
                for part in key_parts:
                    if len(part) >= 3 and part in text_lower:
                        matched = True
                        break

            if matched:
                context = self.get_location_context(key)
                if context:
                    found.append(context)

        return found

    def format_context_injection(self, locations: List[Dict]) -> str:
        """Format location contexts for injection into narrative context.

        Fog-of-war (Phase 3): a location named in conversation is surfaced, but
        only at the party's knowledge tier:
          full   -> everything (coords, description, travel)
          known  -> macro chart (coords, region, description, travel) tagged 'by reputation'
          fogged -> name/type/region stub + caveat; no coords, description, or travel.
        """
        if not locations:
            return ""

        lines = ["**GEOGRAPHY CONTEXT:**", ""]

        for loc in locations:
            # Fallback mirrors _knowledge_state for dicts not produced by
            # get_location_context (defensive; production callers set "knowledge").
            knowledge = loc.get("knowledge") or (
                "full" if loc.get("explored")
                else "known" if loc.get("known")
                else "fogged"
            )

            if knowledge == "fogged":
                lines.append(f"**{loc['name']}** [{loc['type'].upper()}] [FOGGED]")
                lines.append(f"  Region: {loc['region']}")
                lines.append("  *Surfaced by mention only — party has no first-hand "
                             "knowledge. Do not narrate location/interior specifics as known.*")
                lines.append("")
                continue

            status = "EXPLORED" if knowledge == "full" else "KNOWN — by reputation"
            lines.append(f"**{loc['name']}** [{loc['type'].upper()}] [{status}]")
            lines.append(f"  Region: {loc['region']}")
            lines.append(f"  Coordinates: {loc['coordinates']}")

            if loc.get("description"):
                lines.append(f"  {loc['description']}")

            # Travel info (full + known both get the macro chart)
            if loc.get("from_party"):
                party_info = loc["from_party"]
                if party_info.get("is_current_location"):
                    lines.append("  *Party is currently here*")
                else:
                    lines.append(f"  **From {party_info['party_location']}:**")
                    lines.append(f"    Distance: {party_info['hexes']} hexes (~{party_info['miles_approx']} miles)")
                    if party_info.get("days_foot"):
                        lines.append(f"    Travel: {party_info['days_foot']} days on foot")
                        if party_info.get("days_ornithopter"):
                            lines.append(f"    By ornithopter: {party_info['days_ornithopter']} days")
                        lines.append(f"    Hazard: {party_info['hazard']}")
                    elif party_info.get("days_foot_estimate"):
                        lines.append(f"    Travel (est): ~{party_info['days_foot_estimate']} days on foot")

            lines.append("")

        return "\n".join(lines)

    # ========================================
    # MAP RENDERING
    # ========================================

    def render_map(
        self,
        center: str = "ceruline",
        radius: int = 8,
        show_routes: bool = True,
        show_unexplored: bool = True,
        fog_of_war: bool = False,
        resolution: str = "compact"
    ) -> str:
        """Render ASCII overworld map centered on a location."""
        max_label_width = 14 if resolution == "compact" else 40
        data = self._load_geography()

        # Get center coordinates
        center_key = center.lower().replace(" ", "_").replace("'", "")
        if center_key not in data["locations"]:
            return f"Center location '{center}' not found"

        center_loc = data["locations"][center_key]
        cx, cy = center_loc["x"], center_loc["y"]

        # Build coordinate map of locations within radius
        loc_map = {}
        for key, loc in data["locations"].items():
            dist = self._hex_distance(cx, cy, loc["x"], loc["y"])
            if dist <= radius:
                knowledge = self._knowledge_state(loc)
                if show_unexplored or loc["explored"]:
                    loc_map[(loc["x"], loc["y"])] = {
                        "key": key,
                        "name": key.replace("_", " ").title(),
                        "type": loc["type"],
                        "explored": loc["explored"],
                        "known": loc.get("known", False),
                        "knowledge": knowledge,
                        "is_center": key == center_key
                    }

        # Determine grid bounds
        min_x = cx - radius
        max_x = cx + radius
        min_y = cy - radius
        max_y = cy + radius

        # Render ASCII map
        return self._render_ascii_map(
            data, loc_map, min_x, max_x, min_y, max_y, cx, cy, center, show_routes, radius, fog_of_war, max_label_width
        )

    def _render_ascii_map(
        self,
        data: Dict,
        loc_map: Dict,
        min_x: int, max_x: int,
        min_y: int, max_y: int,
        center_x: int, center_y: int,
        center_name: str,
        show_routes: bool,
        radius: int,
        fog_of_war: bool = False,
        max_label_width: int = 24
    ) -> str:
        """Render the ASCII map as a hex grid."""

        # Location type glyphs
        GLYPHS = {
            "arcology": "◆",
            "vault": "▣",
            "crossroads": "✦",
            "camp": "△",
            "ruin": "▢",
            "landmark": "◇",
            "oracle": "◈",
            "terrain": "~",
            "anomaly": "⚠",
            "arcology_ruin": "⬙",
            "arcology_coastal": "◐",
            "cave_system": "◬",
            "settlement": "⌂",
            "default": "○"
        }

        # Hex cell dimensions — content width auto-sizes to the longest label.
        labels = [loc["name"].replace("_", " ").title() for loc in loc_map.values()]
        longest = max((len(l) for l in labels), default=9)
        content_w = max(9, min(longest, max_label_width))
        HEX_W = content_w + 2       # Characters wide for content (incl. border slashes)
        H_SPACING = HEX_W - 1       # Horizontal distance between hex centers
        V_SPACING = 4               # Vertical distance between row centers

        cols = max_x - min_x + 1
        rows = max_y - min_y + 1

        # Grid dimensions
        grid_w = cols * H_SPACING + HEX_W + 10
        grid_h = rows * V_SPACING + 8

        # Initialize grid with spaces
        grid = [[' ' for _ in range(grid_w)] for _ in range(grid_h)]

        def write(gx, gy, text):
            """Write string to grid."""
            for i, ch in enumerate(text):
                if 0 <= gy < grid_h and 0 <= gx + i < grid_w:
                    grid[gy][gx + i] = ch

        def draw_hex(cx, cy, label="", glyph="", knowledge="full", is_center=False):
            """Draw a hex at grid position, styled by knowledge tier.

            Art is built from content_w (closure scope) so the cell auto-sizes
            to the longest label. The glyph sits centred among the underscores
            on the bottom border; the label is centred between the slashes.
            """
            # Underscores flanking the glyph on the bottom border (total = content_w - 1).
            half_left = (content_w - 1) // 2
            half_right = content_w - 1 - half_left
            x0 = cx - (content_w // 2) - 1          # left anchor; keeps hex centred on cx
            if is_center or knowledge == "full":
                write(x0 + 1, cy - 1, "_" * content_w)
                write(x0,     cy,     f"/{label:^{content_w}}\\")
                write(x0,     cy + 1, f"\\{'_' * half_left}{glyph}{'_' * half_right}/")
            else:  # 'known' (reputation) — dashed (spaced) outline
                # Spaced dashes span content_w columns; glyph centred on the
                # bottom border keeps the "- - -" cadence the fog renderer expects.
                top = ("- " * ((content_w + 1) // 2))[:content_w]
                left_dash = ("- " * ((half_left + 1) // 2 + 1))[:half_left]
                right_dash = ("- " * ((half_right + 1) // 2 + 1))[:half_right]
                write(x0 + 1, cy - 1, top)
                write(x0,     cy,     f":{label:^{content_w}}:")
                write(x0,     cy + 1, f" {left_dash}{glyph}{right_dash} ")

        def draw_empty_hex(cx, cy):
            """Draw an unknown hex - subtle marker."""
            write(cx, cy, "?")

        # Draw all hexes
        for ly in range(max_y, min_y - 1, -1):  # North to south
            for lx in range(min_x, max_x + 1):
                row_from_top = max_y - ly
                col = lx - min_x

                # Offset odd columns (staggered hex grid)
                stagger = 2 if (lx % 2 != 0) else 0

                gx = col * H_SPACING + HEX_W // 2 + 4
                gy = row_from_top * V_SPACING + stagger + 3

                if (lx, ly) in loc_map:
                    loc = loc_map[(lx, ly)]
                    knowledge = loc.get("knowledge", "full" if loc.get("explored") else "fogged")
                    # Player-facing fog: a fogged location is not revealed.
                    if fog_of_war and knowledge == "fogged":
                        draw_empty_hex(gx, gy)
                        continue
                    glyph = GLYPHS.get(loc["type"], GLYPHS["default"])

                    # Label fits the auto-sized cell; only cap at the cell width.
                    name = loc["name"].replace("_", " ").title()
                    if len(name) > content_w:
                        name = name[:content_w]

                    draw_hex(gx, gy, name, glyph, knowledge, loc["is_center"])
                else:
                    draw_empty_hex(gx, gy)

        # Convert grid to string
        lines = [''.join(row).rstrip() for row in grid]

        # Trim empty lines
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()

        # Build header
        header = [
            f"VAARN OVERWORLD — Centered on {center_name.title()} (radius {radius})",
            "",
            "                              N",
            "                              ↑",
            ""
        ]

        # Build legend
        legend = [
            "",
            "─" * 60,
            "LEGEND:",
            "  ◆ Arcology   ⬙ Arcology(ruin)   ◐ Arcology(coastal)   ▣ Vault   ✦ Crossroads",
            "  △ Camp   ⌂ Settlement   ◬ Cave   ▢ Ruin   ◇ Landmark   ◈ Oracle   ⚠ Anomaly   ~ Terrain",
            "",
            "  /‾‾‾\\ = Explored (visited)   : - - : = Known (by repute)   ? = Unmapped/fogged",
            "─" * 60
        ]

        return '\n'.join(header + lines + legend)

    def generate_map_file(self) -> str:
        """Generate OVERWORLD_MAP.md file with full map and location index."""
        data = self._load_geography()

        # Render main map
        map_ascii = self.render_map(center="ceruline", radius=10, show_routes=True)

        # Build location index by region
        regions = {}
        for key, loc in data["locations"].items():
            region = loc["region"]
            if region not in regions:
                regions[region] = []
            regions[region].append({
                "key": key,
                "name": key.replace("_", " ").title(),
                "coords": f"({loc['x']}, {loc['y']})",
                "type": loc["type"],
                "explored": loc["explored"],
                "module": loc.get("module"),
                "description": loc.get("description", "")
            })

        # Build markdown content
        lines = [
            "# VAARN OVERWORLD MAP",
            "",
            f"*Auto-generated from VAARN_GEOGRAPHY.json*",
            f"*Last updated: {data['meta'].get('last_updated', 'unknown')}*",
            "",
            "---",
            "",
            "## MAP",
            "",
            "```",
            map_ascii,
            "```",
            "",
            "---",
            "",
            "## LOCATION INDEX",
            ""
        ]

        for region_key, locs in sorted(regions.items()):
            region_name = region_key.replace("_", " ").title()
            region_data = data.get("regions", {}).get(region_key, {})

            lines.append(f"### {region_name}")
            if region_data.get("description"):
                lines.append(f"*{region_data['description']}*")
            lines.append("")

            for loc in sorted(locs, key=lambda x: x["key"]):
                status = "EXPLORED" if loc["explored"] else "PREPPED"
                lines.append(f"**{loc['name']}** {loc['coords']} [{loc['type']}] [{status}]")
                if loc["description"]:
                    lines.append(f"  {loc['description']}")
                if loc["module"]:
                    lines.append(f"  *Module: {loc['module']}*")
                lines.append("")

        lines.extend([
            "---",
            "",
            "## ROUTES",
            "",
            "| From | To | Hexes | Days (foot) | Hazard |",
            "|------|-----|-------|-------------|--------|"
        ])

        for route_key, route in sorted(data["routes"].items()):
            from_name = route["from"].replace("_", " ").title()
            to_name = route["to"].replace("_", " ").title()
            lines.append(
                f"| {from_name} | {to_name} | {route['hexes']} | {route['days_foot']} | {route['hazard_level']} |"
            )

        content = "\n".join(lines)

        # Write to file
        with open(self.map_file, 'w', encoding='utf-8') as f:
            f.write(content)

        return f"Generated OVERWORLD_MAP.md ({len(data['locations'])} locations, {len(data['routes'])} routes)"



    def render_svg(
        self,
        center: str = "ceruline",
        radius: int = None,
        show_unexplored: bool = True,
        hex_size: int = 60,
        show_full_map: bool = False,
        fog_of_war: bool = False
    ) -> str:
        """Render the map as an SVG hex grid."""
        data = self._load_geography()

        # Get center coordinates
        center_key = center.lower().replace(" ", "_").replace("'", "")
        if center_key not in data["locations"]:
            return f"<!-- Error: Center location '{center}' not found -->"

        center_loc = data["locations"][center_key]
        cx, cy = center_loc["x"], center_loc["y"]

        # Build location map - either full map or radius-based
        loc_map = {}

        if show_full_map or radius is None:
            # Show ALL locations - calculate bounds from actual data
            for key, loc in data["locations"].items():
                if show_unexplored or loc["explored"]:
                    knowledge = self._knowledge_state(loc)
                    if fog_of_war and knowledge == "fogged":
                        continue
                    loc_map[(loc["x"], loc["y"])] = {
                        "key": key,
                        "name": key.replace("_", " ").title(),
                        "type": loc["type"],
                        "explored": loc["explored"],
                        "known": loc.get("known", False),
                        "knowledge": knowledge,
                        "is_center": key == center_key,
                        "description": loc.get("description", "")
                    }
        else:
            # Radius-based filtering
            for key, loc in data["locations"].items():
                dist = self._hex_distance(cx, cy, loc["x"], loc["y"])
                if dist <= radius:
                    if show_unexplored or loc["explored"]:
                        knowledge = self._knowledge_state(loc)
                        if fog_of_war and knowledge == "fogged":
                            continue
                        loc_map[(loc["x"], loc["y"])] = {
                            "key": key,
                            "name": key.replace("_", " ").title(),
                            "type": loc["type"],
                            "explored": loc["explored"],
                            "known": loc.get("known", False),
                            "knowledge": knowledge,
                            "is_center": key == center_key,
                            "description": loc.get("description", "")
                        }

        # Calculate actual bounds from locations with padding
        if loc_map:
            all_x = [coord[0] for coord in loc_map.keys()]
            all_y = [coord[1] for coord in loc_map.keys()]
            min_x = min(all_x) - 1  # 1 hex padding
            max_x = max(all_x) + 1
            min_y = min(all_y) - 1
            max_y = max(all_y) + 1
        else:
            # Fallback if no locations
            min_x, max_x = cx - 5, cx + 5
            min_y, max_y = cy - 5, cy + 5

        # SVG hex geometry - flat-top hexagon
        hex_w = hex_size * 2
        hex_h = hex_size * 1.732
        h_spacing = hex_w * 0.75
        v_spacing = hex_h

        cols = max_x - min_x + 1
        rows = max_y - min_y + 1
        svg_w = int(cols * h_spacing + hex_w)
        svg_h = int(rows * v_spacing + hex_h)

        # Vaarn desert color scheme
        COLORS = {
            "bg": "#1a1a2e",
            "hex_empty": "#252540",
            "hex_explored": "#3d5a80",
            "hex_prepped": "#2d3a4a",
            "hex_center": "#5c4d7d",
            "stroke": "#6b7b8c",
            "stroke_explored": "#98c1d9",
            "stroke_prepped": "#4a5568",
            "text": "#e0e0e0",
            "text_dim": "#8899aa",
            "route": "#4a7c59"
        }

        TYPE_COLORS = {
            "arcology": "#c9a227",
            "vault": "#8b5cf6",
            "crossroads": "#22c55e",
            "camp": "#f97316",
            "ruin": "#6b7280",
            "landmark": "#06b6d4",
            "oracle": "#ec4899",
            "terrain": "#a3a3a3",
            "anomaly": "#ef4444",
            "arcology_ruin": "#a16207",
            "arcology_coastal": "#2563eb",
            "cave_system": "#854d0e",
            "settlement": "#65a30d",
            "default": "#9ca3af"
        }

        def hex_points(hx, hy, size):
            points = []
            for i in range(6):
                angle = i * 60
                rad = angle * 3.14159 / 180
                px = hx + size * math.cos(rad)
                py = hy + size * math.sin(rad)
                points.append(f"{px:.1f},{py:.1f}")
            return " ".join(points)

        def grid_to_svg(lx, ly):
            col = lx - min_x
            row = max_y - ly
            offset = v_spacing / 2 if lx % 2 != 0 else 0
            svg_x = col * h_spacing + hex_w / 2 + 20
            svg_y = row * v_spacing + offset + hex_h / 2 + 40
            return svg_x, svg_y

        svg = []
        svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w + 40} {svg_h + 80}">')
        svg.append(f'<rect width="100%" height="100%" fill="{COLORS["bg"]}"/>')
        svg.append(f'<text x="{svg_w/2 + 20}" y="25" text-anchor="middle" fill="{COLORS["text"]}" font-family="sans-serif" font-size="16" font-weight="bold">VAARN OVERWORLD - {center.title()} (r={radius})</text>')
        svg.append(f'<text x="{svg_w + 30}" y="60" text-anchor="middle" fill="{COLORS["text_dim"]}" font-family="sans-serif" font-size="12">N</text>')

        # Routes
        svg.append('<g id="routes">')
        for route_key, route in data["routes"].items():
            from_key, to_key = route["from"], route["to"]
            if from_key not in data["locations"] or to_key not in data["locations"]:
                continue
            from_loc, to_loc = data["locations"][from_key], data["locations"][to_key]
            from_coords, to_coords = (from_loc["x"], from_loc["y"]), (to_loc["x"], to_loc["y"])
            if from_coords in loc_map and to_coords in loc_map:
                x1, y1 = grid_to_svg(from_loc["x"], from_loc["y"])
                x2, y2 = grid_to_svg(to_loc["x"], to_loc["y"])
                svg.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{COLORS["route"]}" stroke-width="3" stroke-dasharray="8,4" opacity="0.6"/>')
        svg.append('</g>')

        # Hexes
        svg.append('<g id="hexes">')
        for ly in range(max_y, min_y - 1, -1):
            for lx in range(min_x, max_x + 1):
                svg_x, svg_y = grid_to_svg(lx, ly)
                if (lx, ly) in loc_map:
                    loc = loc_map[(lx, ly)]
                    type_color = TYPE_COLORS.get(loc["type"], TYPE_COLORS["default"])
                    loc_knowledge = loc.get("knowledge", "fogged")
                    if loc["is_center"]:
                        fill, stroke, stroke_w = COLORS["hex_center"], type_color, 3
                    elif loc_knowledge == "full":
                        fill, stroke, stroke_w = COLORS["hex_explored"], COLORS["stroke_explored"], 2
                    else:
                        fill, stroke, stroke_w = COLORS["hex_prepped"], COLORS["stroke_prepped"], 1.5
                    svg.append(f'<polygon points="{hex_points(svg_x, svg_y, hex_size)}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w}"/>')
                    svg.append(f'<circle cx="{svg_x:.1f}" cy="{svg_y - 15:.1f}" r="6" fill="{type_color}"/>')
                    name = loc["name"]
                    svg.append(f'<text x="{svg_x:.1f}" y="{svg_y + 5:.1f}" text-anchor="middle" fill="{COLORS["text"]}" font-family="sans-serif" font-size="11">{name}</text>')
                    if not fog_of_war:
                        status = "explored" if loc_knowledge == "full" else "known"
                        svg.append(f'<text x="{svg_x:.1f}" y="{svg_y + 20:.1f}" text-anchor="middle" fill="{COLORS["text_dim"]}" font-family="sans-serif" font-size="9">{status}</text>')
                else:
                    svg.append(f'<polygon points="{hex_points(svg_x, svg_y, hex_size)}" fill="{COLORS["hex_empty"]}" stroke="{COLORS["stroke"]}" stroke-width="0.5" opacity="0.3"/>')
        svg.append('</g>')

        # Legend
        legend_y = svg_h + 50
        svg.append(f'<g id="legend" transform="translate(20, {legend_y})">')
        items = [("arcology", "Arcology"), ("arcology_ruin", "Arcology(ruin)"), ("arcology_coastal", "Arcology(coastal)"),
                 ("vault", "Vault"), ("crossroads", "Crossroads"), ("camp", "Camp"), ("settlement", "Settlement"),
                 ("cave_system", "Cave"), ("ruin", "Ruin"), ("landmark", "Landmark"), ("oracle", "Oracle"),
                 ("terrain", "Terrain"), ("anomaly", "Anomaly")]
        for i, (tk, label) in enumerate(items):
            lx, ly = (i % 4) * 120, (i // 4) * 20
            svg.append(f'<circle cx="{lx + 8}" cy="{ly + 4}" r="5" fill="{TYPE_COLORS.get(tk, "#999")}"/>')
            svg.append(f'<text x="{lx + 20}" y="{ly + 8}" fill="{COLORS["text_dim"]}" font-family="sans-serif" font-size="10">{label}</text>')
        svg.append('</g>')
        svg.append('</svg>')
        return "\n".join(svg)

    def generate_svg_map(self, show_unexplored: bool = True, fog_of_war: bool = False) -> str:
        """Generate SVG map file showing ALL locations."""
        svg_content = self.render_svg(
            center="ceruline",
            show_unexplored=show_unexplored,
            hex_size=50,
            show_full_map=True,  # Show entire map, not radius-limited
            fog_of_war=fog_of_war
        )
        svg_path = self.campaign_dir / "OVERWORLD_MAP.svg"
        with open(svg_path, 'w', encoding='utf-8') as f:
            f.write(svg_content)
        return f"Generated {svg_path}"


# ============================================
# TOOL REGISTRATION
# ============================================

def _get_tool_tags(tool_name: str) -> set[str]:
    """Get tags for a tool from the central mapping."""
    return TOOL_TAGS.get(tool_name, {Safety.ALWAYS})


def register_geography_tools(mcp, campaign_dir: Path):
    """Register consolidated geography tool with the MCP server."""

    geo = GeographySystem(campaign_dir)

    @mcp.tool(
        annotations={"readOnlyHint": False, "idempotentHint": False},
        tags=_get_tool_tags("geography")
    )
    def geography(
        action: str,
        name: str = None,
        x: int = None,
        y: int = None,
        location_type: str = None,
        region: str = None,
        module: str = None,
        explored: bool = False,
        known: bool = False,
        description: str = "",
        field: str = None,
        value: str = None,
        from_loc: str = None,
        to_loc: str = None,
        days_foot: float = None,
        days_ornithopter: float = None,
        hazard_level: str = "moderate",
        notes: str = "",
        origin: str = None,
        destination: str = None,
        center: str = "ceruline",
        radius: int = 8,
        show_routes: bool = True,
        show_unexplored: bool = True,
        explored_only: bool = False,
        location: str = None,
        user_input: str = None,
        fog_of_war: bool = False,
        resolution: str = "compact",
        pace: str = "normal",
        forage: bool = False,
        noisy: bool = False,
        food: int = None,
        water: int = None,
        follower_mouths: int = None
    ) -> str:
        """Reach for this WHEN the party travels overland, a new location is discovered, or you need to render the world map or plan a journey route.

        Vaarn overworld geography system.

        Actions:
            add_location: Add location (name, x, y, location_type, region, module?, explored?, known?, description?)
            update_location: Update field (name, field, value)
            mark_explored: Mark visited (name)
            mark_known: Mark known-of by reputation, not yet visited (name)
            remove_location: Remove location (name)
            add_route: Add route (from_loc, to_loc, days_foot, days_ornithopter?, hazard_level?, notes?)
            get_distance: Get distance (origin, destination)
            journey: travel plan (origin, destination; location_type carries the transport mode e.g. "foot"/"ornithopter" — optional, shows all modes if omitted)
            render_map: ASCII map (center?, radius?, show_routes?, show_unexplored?, fog_of_war?, resolution?)
            query: Query locations (region?, center?, radius?, explored_only?, location_type?)
            list_regions: List all regions
            validate_consistency: Spatial sanity check (coord collisions, dangling routes, unknown regions)
            generate_map: Generate OVERWORLD_MAP.md
            generate_svg: Generate OVERWORLD_MAP.svg (show_unexplored?, fog_of_war?)
            set_party_location: Set party location (location)
            get_party_location: Get party location
            inject_context: Scan for locations (user_input)
            depart: Begin travel (destination; location_type carries transport mode e.g. "foot"/"ornithopter"; origin? overrides+corrects the stored party location; food?/water?/follower_mouths? seed the supply pool — vehicle/cargo provisions)
            arrive: Complete travel — arrive at the pending destination (supply mode is NOT auto-flipped; run the pushed supply(action="arrive") only at a supplied base)
            travel_day: Advance one day along the current journey (pace?, forage?)

        Examples:
            geography(action="add_location", name="Salt Bones", x=3, y=-2, location_type="ruin", region="central_wastes")
            geography(action="get_distance", origin="ceruline", destination="salt_bones")
            geography(action="render_map", center="ceruline", radius=6)
        """
        action = action.lower().strip()

        if action == "add_location":
            if not all([name, x is not None, y is not None, location_type, region]):
                return "Error: add_location requires name, x, y, location_type, region"
            return geo.add_location(name, x, y, location_type, region, module, explored, description, known=known)

        elif action == "update_location":
            if not all([name, field, value]):
                return "Error: update_location requires name, field, value"
            if field in ("explored", "known"):
                value = value.lower() in ("true", "yes", "1")
            elif field in ("x", "y"):
                value = int(value)
            return geo.update_location(name, field, value)

        elif action == "mark_explored":
            if not name:
                return "Error: mark_explored requires name"
            return geo.mark_explored(name)

        elif action == "mark_known":
            if not name:
                return "Error: mark_known requires name"
            return geo.mark_known(name)

        elif action == "remove_location":
            if not name:
                return "Error: remove_location requires name"
            return geo.remove_location(name)

        elif action == "add_route":
            if not all([from_loc, to_loc, days_foot is not None]):
                return "Error: add_route requires from_loc, to_loc, days_foot"
            return geo.add_route(from_loc, to_loc, days_foot, days_ornithopter, hazard_level, notes)

        elif action == "get_distance":
            if not all([origin, destination]):
                return "Error: get_distance requires origin, destination"
            result = geo.get_distance(origin, destination)
            if "error" in result:
                return f"Error: {result['error']}"
            lines = [
                f"**{result['origin']} -> {result['destination']}**",
                "",
                f"Hex distance: {result['hexes']} hexes",
                f"As crow flies: ~{result['as_crow_flies_miles']} miles",
                ""
            ]
            if result.get("route_exists"):
                lines.append("**Canonical Route Data:**")
                lines.append(f"  Days (foot): {result['canonical_days_foot']}")
                if result.get("canonical_days_ornithopter"):
                    lines.append(f"  Days (ornithopter): {result['canonical_days_ornithopter']}")
                lines.append(f"  Hazard: {result['hazard_level']}")
                if result.get("notes"):
                    lines.append(f"  Notes: {result['notes']}")
            else:
                lines.append(f"*No canonical route. Estimated {result['estimated_days_foot']} days on foot.*")
            return "\n".join(lines)

        elif action == "journey":
            if not all([origin, destination]):
                return "Error: journey requires origin, destination"
            return geo.journey(origin, destination, mode=location_type)

        elif action == "render_map":
            return geo.render_map(center, radius, show_routes, show_unexplored, fog_of_war, resolution)

        elif action == "query":
            results = geo.query_locations(region, center, radius, explored_only, location_type)
            if not results:
                return "No locations match the query criteria."
            lines = [f"**{len(results)} locations found:**", ""]
            for loc in results:
                status = "EXPLORED" if loc["explored"] else "PREPPED"
                lines.append(f"**{loc['name'].replace('_', ' ').title()}** ({loc['x']}, {loc['y']})")
                lines.append(f"  [{loc['type']}] [{status}] - {loc['region']}")
                if loc.get("description"):
                    desc = loc["description"][:80] + "..." if len(loc.get("description", "")) > 80 else loc.get("description", "")
                    lines.append(f"  {desc}")
                lines.append("")
            return "\n".join(lines)

        elif action == "list_regions":
            return geo.list_regions()

        elif action == "generate_map":
            return geo.generate_map_file()

        elif action == "generate_svg":
            return geo.generate_svg_map(show_unexplored, fog_of_war=fog_of_war)

        elif action == "set_party_location":
            if not location:
                return "Error: set_party_location requires location"
            return geo.set_party_location(location)

        elif action == "get_party_location":
            loc = geo.get_party_location()
            return f"Party is currently at: {loc.replace('_', ' ').title()}"

        elif action == "inject_context":
            if not user_input:
                return "Error: inject_context requires user_input"
            locations = geo.scan_for_locations(user_input)
            if not locations:
                return ""
            return geo.format_context_injection(locations)

        elif action == "validate_consistency":
            return geo.validate_consistency()

        elif action == "depart":
            if not destination:
                return "Error: depart requires destination"
            _out = geo.travel_depart(destination, mode=(location_type or "foot"),
                                     noisy=noisy, origin=origin)
            if _out.startswith("Error"):
                return _out
            if getattr(geo, "on_depart", None):
                try:
                    # Pass pool seeds through so vehicle/cargo provisions can be
                    # declared at depart time (D134: carried-only false-flagged
                    # the crew Deprived). The supply output is surfaced, not
                    # swallowed — its zero-notes and status ARE the picture.
                    _sup_out = geo.on_depart(food=food, water=water,
                                             follower_mouths=follower_mouths)
                    if isinstance(_sup_out, str) and _sup_out:
                        _out += "\n\n" + _sup_out
                except Exception:
                    pass
            return _out

        elif action == "arrive":
            # No automatic supply flip here: whether this arrival is a supplied
            # base is a DM judgment call — travel_arrive pushes the exact
            # supply(action="arrive") call for the DM to run when it is.
            # (D134: auto-flip read 'abundant' at a dead vault's salt-bore rim.)
            return geo.travel_arrive()

        elif action == "travel_day":
            return geo.travel_day(pace=pace, forage=forage)

        else:
            return f"Unknown action: {action}. Valid actions: add_location, update_location, mark_explored, mark_known, remove_location, add_route, get_distance, journey, render_map, query, list_regions, validate_consistency, generate_map, generate_svg, set_party_location, get_party_location, inject_context, depart, arrive, travel_day"

    return geo
