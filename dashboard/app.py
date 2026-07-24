"""The companion dashboard's Textual App.

DUMB RENDERER: polls player_view.json + player_map.txt (mtime, ~1s) and
re-renders on change. All data-shaping lives in dashboard/model.py so it's
testable without running the TUI; this module is chrome only. Never writes,
never imports server, never opens any campaign file other than the two
player-view artifacts (model.read_artifacts enforces that).
"""
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from dashboard import model

POLL_INTERVAL = 1.0
STALE_SUFFIX = "\n\n[stale -- last good render, file failed to parse]"

_TAB_IDS = ("party", "map", "world", "parleys")


class DashboardApp(App):
    """Read-only companion view for a second terminal pane."""

    TITLE = "Rubicon Seven -- Companion View"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("1", "show_tab('party')", "Party", show=True),
        Binding("2", "show_tab('map')", "Map", show=True),
        Binding("3", "show_tab('world')", "World", show=True),
        Binding("4", "show_tab('parleys')", "Parleys", show=True),
        Binding("left", "prev_tab", "Prev Tab", show=True),
        Binding("right", "next_tab", "Next Tab", show=True),
    ]

    def __init__(self, campaign_dir, **kwargs):
        super().__init__(**kwargs)
        self.campaign_dir = Path(campaign_dir)
        self._view_mtime = None
        self._map_mtime = None
        self._last_view = None
        self._last_map_text = None
        self._stale = False

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="party"):
            with TabPane("Party", id="party"):
                yield VerticalScroll(Static(model.NO_VIEW_PLACEHOLDER, id="party-body", markup=False))
            with TabPane("Map", id="map"):
                yield VerticalScroll(Static(model.NO_VIEW_PLACEHOLDER, id="map-body", markup=False))
            with TabPane("World", id="world"):
                yield VerticalScroll(Static(model.NO_VIEW_PLACEHOLDER, id="world-body", markup=False))
            with TabPane("Journal", id="journal"):
                yield VerticalScroll(Static(model.NO_VIEW_PLACEHOLDER, id="journal-body", markup=False))
            with TabPane("Parleys", id="parleys"):
                yield VerticalScroll(Static(model.NO_VIEW_PLACEHOLDER, id="parleys-body", markup=False))
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(POLL_INTERVAL, self._poll)

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_prev_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        idx = _TAB_IDS.index(tabs.active) if tabs.active in _TAB_IDS else 0
        tabs.active = _TAB_IDS[(idx - 1) % len(_TAB_IDS)]

    def action_next_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        idx = _TAB_IDS.index(tabs.active) if tabs.active in _TAB_IDS else 0
        tabs.active = _TAB_IDS[(idx + 1) % len(_TAB_IDS)]

    def _poll(self) -> None:
        view_path = self.campaign_dir / model.VIEW_FILENAME
        map_path = self.campaign_dir / model.MAP_FILENAME
        view_mtime = model.safe_stat_mtime(view_path)
        map_mtime = model.safe_stat_mtime(map_path)
        if view_mtime != self._view_mtime or map_mtime != self._map_mtime:
            self._view_mtime = view_mtime
            self._map_mtime = map_mtime
            self._refresh()

    def _refresh(self) -> None:
        view, map_text, stale = model.read_artifacts(self.campaign_dir)
        if stale:
            self._stale = True   # keep the last good view, flag it stale
        else:
            self._stale = False
            self._last_view = view  # may legitimately be None (no file yet)

        self._last_map_text = map_text  # plain text has no "malformed" state

        w = model.world_summary(self._last_view)
        if w and w.get("updated_at"):
            self.sub_title = f"as of {model.format_time(w['updated_at'])}"
        else:
            self.sub_title = ""

        self._render_party()
        self._render_map()
        self._render_world()
        self._render_journal()
        self._render_parleys()

    def _suffix(self) -> str:
        return STALE_SUFFIX if self._stale else ""

    def _render_party(self) -> None:
        body = self.query_one("#party-body", Static)
        cards = model.party_cards(self._last_view)
        if not cards:
            body.update(model.NO_VIEW_PLACEHOLDER)
            return
        body.update(model.render_party_text(cards) + self._suffix())

    def _render_map(self) -> None:
        body = self.query_one("#map-body", Static)
        if self._last_map_text is None:
            body.update(model.NO_VIEW_PLACEHOLDER)
            return
        header = ""
        w = model.world_summary(self._last_view)
        if w and w.get("location"):
            header = f"Location: {w['location']}\n\n"
        body.update(header + self._last_map_text + self._suffix())

    def _render_world(self) -> None:
        body = self.query_one("#world-body", Static)
        w = model.world_summary(self._last_view)
        if w is None:
            body.update(model.NO_VIEW_PLACEHOLDER)
            return
        combat = "COMBAT" if w["in_combat"] else "no combat"
        lines = [
            f"Day {w['day']}   {w['weather'] or '?'}",
            f"Location: {w['location'] or '?'}",
            f"Active prep: {w['active_prep'] or '(none)'}",
            f"Supply: {w['supply_mode'] or '?'}   Wealth: {w['wealth_tokens']} tokens",
            combat,
            f"Open parleys: {w['parley_count']}",
        ]
        if w.get("updated_at"):
            lines.append(f"as of {model.format_time(w['updated_at'])}")
        body.update("\n".join(lines) + self._suffix())

    def _render_journal(self) -> None:
        body = self.query_one("#journal-body", Static)
        lines = model.journal_lines(self._last_view)
        if not lines:
            body.update(model.NO_VIEW_PLACEHOLDER)
            return
        body.update("\n".join(lines) + self._suffix())

    def _render_parleys(self) -> None:
        body = self.query_one("#parleys-body", Static)
        parleys = model.parleys_list(self._last_view)
        if not parleys:
            body.update("none open" + self._suffix())
            return
        lines = [f"{p['slug']}   (tier {p['tier']})" for p in parleys]
        body.update("\n".join(lines) + self._suffix())


def run(campaign_dir) -> None:
    DashboardApp(campaign_dir).run()
