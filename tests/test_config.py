"""config.project_path(): data paths resolve against the checkout root, so
running from another working directory finds the same data."""

from pathlib import Path

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


def test_env_overridable_defaults_live_under_var(monkeypatch):
    monkeypatch.delenv("CHROMA_DIR", raising=False)
    monkeypatch.delenv("TRACE_LOG_PATH", raising=False)
    assert config.env_path("CHROMA_DIR", "var/chroma_db") == str(PROJECT_ROOT / "var" / "chroma_db")
    monkeypatch.setenv("TRACE_LOG_PATH", "")
    assert config.env_path("TRACE_LOG_PATH", "var/trace_logs/traces.jsonl") == ""
    monkeypatch.setenv("CHROMA_DIR", "elsewhere/db")
    assert Path(config.env_path("CHROMA_DIR", "var/chroma_db")) == PROJECT_ROOT / "elsewhere" / "db"
