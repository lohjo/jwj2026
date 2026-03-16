"""Tests for db/run_sql.py — SQL execution utilities."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Stable path to the db/sql directory, regardless of where the test file lives.
_DB_SQL_DIR = Path(__file__).parent.parent / "db" / "sql"


def _make_client():
    """Return a minimal MagicMock that satisfies run_sql's client interface."""
    client = MagicMock()
    client.command.return_value = 1  # SELECT 1
    return client


# ---------------------------------------------------------------------------
# get_client
# ---------------------------------------------------------------------------

def test_get_client_uses_config_constants():
    """get_client() should build the connection from config constants, not os.getenv."""
    import config
    mock_client = MagicMock()
    with patch("db.run_sql.clickhouse_connect") as mock_cc, \
         patch.object(config, "CLICKHOUSE_HOST", "test-host"), \
         patch.object(config, "CLICKHOUSE_PORT", 9440), \
         patch.object(config, "CLICKHOUSE_USER", "test-user"), \
         patch.object(config, "CLICKHOUSE_PASSWORD", "test-pass"):
        mock_cc.get_client.return_value = mock_client

        import db.run_sql as mod
        # Re-bind the module-level names to the patched config values
        with patch.object(mod, "CLICKHOUSE_HOST", "test-host"), \
             patch.object(mod, "CLICKHOUSE_PORT", 9440), \
             patch.object(mod, "CLICKHOUSE_USER", "test-user"), \
             patch.object(mod, "CLICKHOUSE_PASSWORD", "test-pass"):
            mod.get_client()

        mock_cc.get_client.assert_called_once_with(
            host="test-host",
            port=9440,
            username="test-user",
            password="test-pass",
            secure=True,
            connect_timeout=30,
            send_receive_timeout=60,
        )


# ---------------------------------------------------------------------------
# execute_sql_file
# ---------------------------------------------------------------------------

def test_execute_sql_file_runs_statements(tmp_path):
    """execute_sql_file() splits on ';' and calls client.command() for each statement."""
    sql_file = tmp_path / "test.sql"
    sql_file.write_text("SELECT 1;\nSELECT 2;\n", encoding="utf-8")

    client = _make_client()
    from db.run_sql import execute_sql_file
    execute_sql_file(client, str(sql_file))

    assert client.command.call_count == 2
    calls = [c.args[0] for c in client.command.call_args_list]
    assert "SELECT 1" in calls[0]
    assert "SELECT 2" in calls[1]


def test_execute_sql_file_strips_comments(tmp_path):
    """execute_sql_file() ignores full-line SQL comments."""
    sql_file = tmp_path / "test.sql"
    sql_file.write_text("-- this is a comment\nSELECT 1;\n", encoding="utf-8")

    client = _make_client()
    from db.run_sql import execute_sql_file
    execute_sql_file(client, str(sql_file))

    assert client.command.call_count == 1
    stmt = client.command.call_args.args[0]
    assert "--" not in stmt


def test_execute_sql_file_reraises_on_failure(tmp_path):
    """execute_sql_file() re-raises if client.command() fails."""
    sql_file = tmp_path / "test.sql"
    sql_file.write_text("SELECT bad;\n", encoding="utf-8")

    client = _make_client()
    client.command.side_effect = RuntimeError("syntax error")

    from db.run_sql import execute_sql_file
    with pytest.raises(RuntimeError, match="syntax error"):
        execute_sql_file(client, str(sql_file))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def test_main_discovers_sql_dir_relative_to_module(tmp_path, monkeypatch):
    """main() with no argv should look in <module_dir>/sql/*.sql."""
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "00_test.sql").write_text("SELECT 1;", encoding="utf-8")

    mock_client = _make_client()

    import db.run_sql as mod
    monkeypatch.setattr(sys, "argv", ["run_sql"])

    with patch.object(mod, "get_client", return_value=mock_client), \
         patch("db.run_sql.glob.glob", return_value=[str(sql_dir / "00_test.sql")]):
        mod.main()

    mock_client.command.assert_any_call("SELECT 1")


def test_main_exits_when_no_sql_files(monkeypatch, capsys):
    """main() should call sys.exit(1) when no SQL files are found."""
    import db.run_sql as mod
    monkeypatch.setattr(sys, "argv", ["run_sql"])

    with patch("db.run_sql.glob.glob", return_value=[]):
        with pytest.raises(SystemExit) as exc_info:
            mod.main()
    assert exc_info.value.code == 1


def test_main_uses_argv_files(monkeypatch, tmp_path):
    """main() should use explicit file paths from sys.argv."""
    sql_file = tmp_path / "custom.sql"
    sql_file.write_text("SELECT 42;", encoding="utf-8")

    mock_client = _make_client()

    import db.run_sql as mod
    monkeypatch.setattr(sys, "argv", ["run_sql", str(sql_file)])

    with patch.object(mod, "get_client", return_value=mock_client):
        mod.main()

    # Should have executed SELECT 42
    stmts = [c.args[0] for c in mock_client.command.call_args_list]
    assert any("SELECT 42" in s for s in stmts)


# ---------------------------------------------------------------------------
# Schema files exist
# ---------------------------------------------------------------------------

def test_sql_schema_files_exist():
    """The three expected SQL schema files must exist under db/sql/."""
    assert (_DB_SQL_DIR / "00_create_db.sql").exists(), "00_create_db.sql missing"
    assert (_DB_SQL_DIR / "01_detection_events.sql").exists(), "01_detection_events.sql missing"
    assert (_DB_SQL_DIR / "02_materialized_views.sql").exists(), "02_materialized_views.sql missing"


def test_detection_events_schema_has_required_columns():
    """01_detection_events.sql must define all columns used by log_to_clickhouse()."""
    sql = (_DB_SQL_DIR / "01_detection_events.sql").read_text()
    required_columns = [
        "event_id",
        "user_id",
        "session_id",
        "content_type",
        "source_language",
        "content_preview",
        "guard_label",
        "guard_verdict",
        "misinfo_detected",
        "misinfo_type",
        "manipulation_detected",
        "manipulation_type",
        "explanation",
        "is_harmful",
        "processing_ms",
        "model_versions",
        "error_code",
    ]
    for col in required_columns:
        assert col in sql, f"Column '{col}' missing from detection_events schema"
