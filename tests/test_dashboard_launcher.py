"""Tests for scripts/dashboard.py's campaign-dir resolution logic.

resolve_campaign_dir is a pure function (repo_root/argv/env passed in), so
these exercise it directly without touching sys.argv or the real environment.
"""
import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "dashboard.py"


def _load_dashboard_script():
    """Import scripts/dashboard.py as a module without requiring textual
    to be importable at module scope (it's imported lazily inside)."""
    spec = importlib.util.spec_from_file_location("dashboard_launcher_script", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["dashboard_launcher_script"] = module
    spec.loader.exec_module(module)
    return module


dashboard_script = _load_dashboard_script()


def test_resolve_prefers_argv(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    result, source = dashboard_script.resolve_campaign_dir(
        ["prog", "/explicit/dir"], {}, repo_root)
    assert result == "/explicit/dir"
    assert source == "arg"


def test_resolve_falls_back_to_env(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    result, source = dashboard_script.resolve_campaign_dir(
        ["prog"], {"RUBICON_CAMPAIGN_DIR": "/env/dir"}, repo_root)
    assert result == "/env/dir"
    assert source == "env"


def test_resolve_falls_back_to_sibling_default_when_it_exists(tmp_path):
    repo_root = tmp_path / "rubicon-seven-mcp"
    repo_root.mkdir()
    sibling = tmp_path / "rubicon-seven-campaign"
    sibling.mkdir()
    result, source = dashboard_script.resolve_campaign_dir(["prog"], {}, repo_root)
    assert result == str(sibling)
    assert source == "sibling-default"


def test_resolve_returns_none_when_nothing_found(tmp_path):
    repo_root = tmp_path / "rubicon-seven-mcp"
    repo_root.mkdir()
    result, source = dashboard_script.resolve_campaign_dir(["prog"], {}, repo_root)
    assert result is None
    assert source is None


def test_arg_and_env_take_priority_over_existing_sibling(tmp_path):
    repo_root = tmp_path / "rubicon-seven-mcp"
    repo_root.mkdir()
    (tmp_path / "rubicon-seven-campaign").mkdir()
    result, source = dashboard_script.resolve_campaign_dir(
        ["prog", "/explicit/dir"], {"RUBICON_CAMPAIGN_DIR": "/env/dir"}, repo_root)
    assert result == "/explicit/dir"
    assert source == "arg"
