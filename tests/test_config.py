"""config.project_path(): data paths resolve against the checkout root, so
running from another working directory finds the same data."""

import importlib
from pathlib import Path

import pytest

from sec_agent import config
from sec_agent.config import PROJECT_ROOT, project_path


def test_relative_path_resolves_against_the_project_root():
    assert project_path("var/chroma_db") == str(PROJECT_ROOT / "var" / "chroma_db")
    assert project_path("./chroma_db") == str(PROJECT_ROOT / "chroma_db")


def test_absolute_path_is_unchanged(tmp_path):
    assert project_path(str(tmp_path)) == str(tmp_path)


def test_empty_value_stays_empty():
    # An empty TRACE_LOG_PATH is how the local trace log is disabled.
    assert project_path("") == ""


def test_project_root_is_the_checkout():
    assert (PROJECT_ROOT / "pyproject.toml").is_file()


def test_data_dirs_live_under_var():
    var = PROJECT_ROOT / "var"
    assert config.VAR_DIR == var
    for path in (config.DATA_DIR, config.CHUNKS_DIR, config.XBRL_CACHE_DIR):
        assert path.parent == var


@pytest.fixture
def reload_config(monkeypatch):
    """Re-runs config.py's module body with .env loading stubbed out, so the
    developer's own .env can't mask the defaults under test; reloads the
    real config back afterwards."""

    def reload(**env):
        monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
        for name, value in env.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        return importlib.reload(config)

    yield reload
    # Undo the patches first, or the restoring reload would run under them.
    monkeypatch.undo()
    importlib.reload(config)


def test_env_overridable_defaults_live_under_var(reload_config):
    reloaded = reload_config(CHROMA_DIR=None, TRACE_LOG_PATH=None)
    assert reloaded.CHROMA_DIR == str(PROJECT_ROOT / "var" / "chroma_db")
    assert reloaded.TRACE_LOG_PATH == str(PROJECT_ROOT / "var" / "trace_logs" / "traces.jsonl")


def test_env_overrides_resolve_against_the_root(reload_config):
    reloaded = reload_config(CHROMA_DIR="elsewhere/db", TRACE_LOG_PATH="")
    assert Path(reloaded.CHROMA_DIR) == PROJECT_ROOT / "elsewhere" / "db"
    assert reloaded.TRACE_LOG_PATH == ""
