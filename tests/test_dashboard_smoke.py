"""Smoke test for the Textual dashboard app itself.

The data-shaping logic is covered without the TUI in test_dashboard_contract.py;
this only proves the App boots and its tab structure is present, via Textual's
own headless run_test() pilot. Driven with a plain asyncio.run() wrapper so no
extra pytest-asyncio/anyio plugin config is needed.
"""
import asyncio

from dashboard.app import DashboardApp


def test_app_mounts_with_expected_tabs(tmp_path):
    async def _drive():
        app = DashboardApp(tmp_path)
        async with app.run_test() as pilot:
            tab_ids = {pane.id for pane in app.query("TabPane")}
            assert tab_ids == {"party", "map", "world", "journal", "parleys"}

    asyncio.run(_drive())
