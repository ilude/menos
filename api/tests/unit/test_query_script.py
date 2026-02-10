"""Unit tests for scripts/query.py."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from scripts.query import (
    format_table,
    load_env_file,
    main,
    parse_results,
    run_query,
)


class TestParseResults:
    """Tests for parse_results function."""

    def test_none_input_returns_empty_list(self):
        assert parse_results(None) == []

    def test_empty_list_returns_empty_list(self):
        assert parse_results([]) == []

    def test_non_list_returns_empty_list(self):
        assert parse_results("string") == []

    def test_v1_wrapped_format(self):
        result = [{"result": [{"id": "1", "name": "test"}]}]
        parsed = parse_results(result)
        assert parsed == [{"id": "1", "name": "test"}]

    def test_v2_flat_format(self):
        result = [{"id": "1", "name": "test"}]
        parsed = parse_results(result)
        assert parsed == [{"id": "1", "name": "test"}]

    def test_converts_record_id_objects(self):
        record_id = MagicMock()
        record_id.id = "content:abc123"
        result = [{"id": record_id, "title": "hello"}]
        parsed = parse_results(result)
        assert parsed == [{"id": "content:abc123", "title": "hello"}]

    def test_preserves_normal_values(self):
        result = [{"name": "test", "count": 42, "meta": {"nested": True}}]
        parsed = parse_results(result)
        assert parsed == [{"name": "test", "count": 42, "meta": {"nested": True}}]

    def test_mixed_record_id_and_normal(self):
        record_id = MagicMock()
        record_id.id = "chunk:xyz"
        result = [{"id": record_id, "text": "hello", "score": 0.95}]
        parsed = parse_results(result)
        assert parsed[0]["id"] == "chunk:xyz"
        assert parsed[0]["text"] == "hello"
        assert parsed[0]["score"] == 0.95


class TestFormatTable:
    """Tests for format_table function."""

    def test_empty_rows_prints_no_results(self, capsys):
        format_table([])
        captured = capsys.readouterr()
        assert "(no results)" in captured.out

    def test_single_row_prints_header_and_data(self, capsys):
        format_table([{"name": "alice", "age": "30"}])
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert "name" in lines[0]
        assert "age" in lines[0]
        assert "----" in lines[1]
        assert "alice" in lines[2]
        assert "30" in lines[2]

    def test_multiple_rows_aligned(self, capsys):
        rows = [
            {"name": "alice", "role": "admin"},
            {"name": "bob", "role": "user"},
            {"name": "charlie", "role": "moderator"},
        ]
        format_table(rows)
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        # Header + separator + 3 data rows + blank + footer = 7
        assert len(lines) == 7
        assert "charlie" in lines[4]

    def test_column_width_capped_at_80(self, capsys):
        long_value = "x" * 120
        format_table([{"col": long_value}])
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        # Data line should be truncated to 80 chars for the column
        data_line = lines[2]
        # The value portion should not exceed 80 chars
        assert len(data_line.strip()) <= 80

    def test_singular_row_footer(self, capsys):
        format_table([{"a": "1"}])
        captured = capsys.readouterr()
        assert "(1 row)" in captured.out
        assert "(1 rows)" not in captured.out

    def test_plural_rows_footer(self, capsys):
        rows = [{"a": "1"}, {"a": "2"}, {"a": "3"}]
        format_table(rows)
        captured = capsys.readouterr()
        assert "(3 rows)" in captured.out

    def test_missing_keys_across_rows(self, capsys):
        rows = [
            {"name": "alice", "email": "alice@test.com"},
            {"name": "bob", "phone": "555-1234"},
        ]
        format_table(rows)
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        header = lines[0]
        assert "name" in header
        assert "email" in header
        assert "phone" in header

    def test_column_order_matches_first_appearance(self, capsys):
        rows = [
            {"zebra": "1", "apple": "2"},
            {"apple": "3", "mango": "4"},
        ]
        format_table(rows)
        captured = capsys.readouterr()
        header = captured.out.split("\n")[0]
        zebra_pos = header.index("zebra")
        apple_pos = header.index("apple")
        mango_pos = header.index("mango")
        assert zebra_pos < apple_pos < mango_pos


class TestLoadEnvFile:
    """Tests for load_env_file function."""

    @pytest.fixture
    def env_setup(self, tmp_path, monkeypatch):
        """Set up a fake directory structure so load_env_file finds .env in tmp_path."""
        # load_env_file does: Path(__file__).resolve().parent.parent.parent / ".env"
        # So we need __file__ to be at tmp_path/api/scripts/query.py
        fake_script = tmp_path / "api" / "scripts" / "query.py"
        fake_script.parent.mkdir(parents=True, exist_ok=True)
        fake_script.touch()
        monkeypatch.setattr("scripts.query.__file__", str(fake_script))
        return tmp_path

    def test_loads_key_value_pairs(self, env_setup, monkeypatch):
        env_file = env_setup / ".env"
        env_file.write_text("MY_TEST_KEY=my_test_value\n")
        monkeypatch.delenv("MY_TEST_KEY", raising=False)
        load_env_file()
        assert os.environ["MY_TEST_KEY"] == "my_test_value"
        monkeypatch.delenv("MY_TEST_KEY", raising=False)

    def test_skips_comments_and_blank_lines(self, env_setup, monkeypatch):
        env_file = env_setup / ".env"
        env_file.write_text("# this is a comment\n\nVALID_KEY=valid_value\n")
        monkeypatch.delenv("VALID_KEY", raising=False)
        load_env_file()
        assert os.environ["VALID_KEY"] == "valid_value"
        monkeypatch.delenv("VALID_KEY", raising=False)

    def test_handles_export_prefix(self, env_setup, monkeypatch):
        env_file = env_setup / ".env"
        env_file.write_text("export EXPORTED_VAR=exported_val\n")
        monkeypatch.delenv("EXPORTED_VAR", raising=False)
        load_env_file()
        assert os.environ["EXPORTED_VAR"] == "exported_val"
        monkeypatch.delenv("EXPORTED_VAR", raising=False)

    def test_strips_single_and_double_quotes(self, env_setup, monkeypatch):
        env_file = env_setup / ".env"
        env_file.write_text("SINGLE_Q='single_val'\nDOUBLE_Q=\"double_val\"\n")
        monkeypatch.delenv("SINGLE_Q", raising=False)
        monkeypatch.delenv("DOUBLE_Q", raising=False)
        load_env_file()
        assert os.environ["SINGLE_Q"] == "single_val"
        assert os.environ["DOUBLE_Q"] == "double_val"
        monkeypatch.delenv("SINGLE_Q", raising=False)
        monkeypatch.delenv("DOUBLE_Q", raising=False)

    def test_does_not_overwrite_existing_env_vars(self, env_setup, monkeypatch):
        env_file = env_setup / ".env"
        env_file.write_text("EXISTING_VAR=new_value\n")
        monkeypatch.setenv("EXISTING_VAR", "original_value")
        load_env_file()
        assert os.environ["EXISTING_VAR"] == "original_value"

    def test_handles_missing_env_file(self, env_setup):
        # No .env file created — should not raise
        load_env_file()

    def test_handles_values_with_equals_sign(self, env_setup, monkeypatch):
        env_file = env_setup / ".env"
        env_file.write_text("COMPLEX_VAL=foo=bar=baz\n")
        monkeypatch.delenv("COMPLEX_VAL", raising=False)
        load_env_file()
        assert os.environ["COMPLEX_VAL"] == "foo=bar=baz"
        monkeypatch.delenv("COMPLEX_VAL", raising=False)


class TestQuerySafety:
    """Tests for dangerous query blocking in run_query."""

    @pytest.fixture
    def mock_surreal(self):
        with patch("scripts.query.Surreal") as mock_cls:
            mock_db = MagicMock()
            mock_cls.return_value = mock_db
            mock_db.query.return_value = []
            yield mock_cls, mock_db

    def test_blocks_delete(self, mock_surreal):
        with pytest.raises(SystemExit) as exc_info:
            import asyncio
            asyncio.run(run_query("DELETE FROM content"))
        assert exc_info.value.code == 1

    def test_blocks_update(self, mock_surreal):
        with pytest.raises(SystemExit):
            import asyncio
            asyncio.run(run_query("UPDATE content SET title='x'"))

    def test_blocks_create(self, mock_surreal):
        with pytest.raises(SystemExit):
            import asyncio
            asyncio.run(run_query("CREATE content SET title='x'"))

    def test_blocks_remove(self, mock_surreal):
        with pytest.raises(SystemExit):
            import asyncio
            asyncio.run(run_query("REMOVE TABLE content"))

    def test_blocks_define(self, mock_surreal):
        with pytest.raises(SystemExit):
            import asyncio
            asyncio.run(run_query("DEFINE TABLE test"))

    def test_case_insensitive(self, mock_surreal):
        for variant in ["delete FROM x", "Delete FROM x", "DELETE FROM x"]:
            with pytest.raises(SystemExit):
                import asyncio
                asyncio.run(run_query(variant))

    def test_strips_leading_whitespace(self, mock_surreal):
        with pytest.raises(SystemExit):
            import asyncio
            asyncio.run(run_query("  DELETE FROM content"))

    def test_allows_select(self, mock_surreal):
        import asyncio
        asyncio.run(run_query("SELECT * FROM content"))
        _, mock_db = mock_surreal
        mock_db.query.assert_called_once_with("SELECT * FROM content")

    def test_allows_info(self, mock_surreal):
        import asyncio
        asyncio.run(run_query("INFO FOR DB"))
        _, mock_db = mock_surreal
        mock_db.query.assert_called_once_with("INFO FOR DB")


class TestRunQuery:
    """Tests for run_query function."""

    @pytest.fixture
    def mock_surreal(self):
        with patch("scripts.query.Surreal") as mock_cls:
            mock_db = MagicMock()
            mock_cls.return_value = mock_db
            mock_db.query.return_value = [{"id": "1", "name": "test"}]
            yield mock_cls, mock_db

    def test_table_output_default(self, mock_surreal, capsys):
        import asyncio
        asyncio.run(run_query("SELECT * FROM content"))
        captured = capsys.readouterr()
        assert "name" in captured.out
        assert "test" in captured.out

    def test_json_output_flag(self, mock_surreal, capsys):
        import asyncio
        asyncio.run(run_query("SELECT * FROM content", output_json=True))
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)
        assert parsed[0]["name"] == "test"

    def test_reads_password_from_env(self, mock_surreal, monkeypatch):
        monkeypatch.setenv("SURREALDB_PASSWORD", "secret123")
        _, mock_db = mock_surreal
        import asyncio
        asyncio.run(run_query("SELECT * FROM content"))
        mock_db.signin.assert_called_once_with(
            {"username": "root", "password": "secret123"}
        )

    def test_falls_back_to_default_password(self, mock_surreal, monkeypatch):
        monkeypatch.delenv("SURREALDB_PASSWORD", raising=False)
        _, mock_db = mock_surreal
        import asyncio
        asyncio.run(run_query("SELECT * FROM content"))
        mock_db.signin.assert_called_once_with(
            {"username": "root", "password": "root"}
        )

    def test_connects_to_provided_url(self, mock_surreal):
        mock_cls, _ = mock_surreal
        import asyncio
        asyncio.run(run_query("SELECT 1", db_url="http://localhost:9999"))
        mock_cls.assert_called_once_with("http://localhost:9999")

    def test_uses_correct_namespace_and_database(self, mock_surreal):
        _, mock_db = mock_surreal
        import asyncio
        asyncio.run(run_query("SELECT 1"))
        mock_db.use.assert_called_once_with("menos", "menos")


class TestMainCLI:
    """Tests for main CLI entry point."""

    def test_requires_query_argument(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["query.py"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2  # argparse exits with 2 for missing args

    def test_passes_query_to_run_query(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv", ["query.py", "SELECT * FROM content"]
        )
        calls = []

        async def fake_run_query(query, output_json, db_url):
            calls.append((query, output_json, db_url))

        monkeypatch.setattr("scripts.query.load_env_file", lambda: None)
        monkeypatch.setattr("scripts.query.run_query", fake_run_query)
        main()
        assert len(calls) == 1
        assert calls[0][0] == "SELECT * FROM content"

    def test_json_flag_parsed(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv", ["query.py", "--json", "SELECT 1"]
        )
        calls = []

        async def fake_run_query(query, output_json, db_url):
            calls.append((query, output_json, db_url))

        monkeypatch.setattr("scripts.query.load_env_file", lambda: None)
        monkeypatch.setattr("scripts.query.run_query", fake_run_query)
        main()
        assert calls[0][1] is True

    def test_custom_db_url(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["query.py", "--db-url", "http://custom:8080", "SELECT 1"],
        )
        calls = []

        async def fake_run_query(query, output_json, db_url):
            calls.append((query, output_json, db_url))

        monkeypatch.setattr("scripts.query.load_env_file", lambda: None)
        monkeypatch.setattr("scripts.query.run_query", fake_run_query)
        main()
        assert calls[0][2] == "http://custom:8080"

    def test_calls_load_env_file_before_query(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv", ["query.py", "SELECT 1"]
        )
        call_order = []

        def fake_load_env():
            call_order.append("load_env")

        async def fake_run_query(query, output_json, db_url):
            call_order.append("run_query")

        monkeypatch.setattr("scripts.query.load_env_file", fake_load_env)
        monkeypatch.setattr("scripts.query.run_query", fake_run_query)
        main()
        assert call_order == ["load_env", "run_query"]
