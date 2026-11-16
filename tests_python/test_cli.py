# -*- coding: utf-8 -*-

import pytest

from agent_app import cli


class TestAsWordList:
    """
    fire hands `--retired` over in three different shapes, so normalizing it is
    the one piece of parsing this module still does by hand.
    """

    def test_empty_string_is_no_words(self):
        assert cli._as_word_list("") == []

    def test_a_single_word_arrives_as_a_string(self):
        assert cli._as_word_list("widget") == ["widget"]

    def test_a_comma_list_arrives_as_a_tuple(self):
        """`--retired "widget,part"` is split by fire before we ever see it."""
        assert cli._as_word_list(("widget", "part")) == ["widget", "part"]

    def test_a_comma_string_is_split_too(self):
        """Called directly rather than through fire, it is still one string."""
        assert cli._as_word_list("widget,part") == ["widget", "part"]

    def test_blanks_and_empties_are_dropped(self):
        assert cli._as_word_list("widget, part,, ") == ["widget", "part"]


class TestCheckContent:
    def test_passes_the_words_through(self, monkeypatch):
        seen = {}

        def fake_run(retired=None):
            seen["retired"] = retired
            return 0

        monkeypatch.setattr("agent_app.content_check.run", fake_run)
        with pytest.raises(SystemExit) as exc:
            cli.Cli().check_content()
        assert exc.value.code == 0
        assert seen["retired"] == []

    def test_splits_and_strips(self, monkeypatch):
        seen = {}

        def fake_run(retired=None):
            seen["retired"] = retired
            return 0

        monkeypatch.setattr("agent_app.content_check.run", fake_run)
        with pytest.raises(SystemExit):
            cli.Cli().check_content(retired="widget, part,, ")
        assert seen["retired"] == ["widget", "part"]

    def test_a_failed_check_exits_nonzero(self, monkeypatch):
        """
        The whole reason these commands raise instead of returning: fire prints
        a returned value and exits 0, which would make a failure look green.
        """
        monkeypatch.setattr("agent_app.content_check.run", lambda retired=None: 1)
        with pytest.raises(SystemExit) as exc:
            cli.Cli().check_content()
        assert exc.value.code == 1


class TestGenData:
    def test_runs_the_single_generator_and_replaces_old_files(self, monkeypatch, tmp_path):
        import subprocess

        (tmp_path / "04-acme_widgets_data_generator.py").touch()
        (tmp_path / "old.duckdb").touch()
        monkeypatch.setattr("agent_app.warehouse.engines.DIR_DATASET", tmp_path)
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(SystemExit) as exc:
            cli.Cli().gen_data(seed=7)
        assert exc.value.code == 0
        assert not (tmp_path / "old.duckdb").exists()
        assert calls[0][-2:] == ["--seed", "7"]

    def test_no_generator_exits_one(self, monkeypatch, tmp_path):
        monkeypatch.setattr("agent_app.warehouse.engines.DIR_DATASET", tmp_path)
        with pytest.raises(SystemExit) as exc:
            cli.Cli().gen_data()
        assert exc.value.code == 1


class TestTestDbConn:
    """
    No network here. What is worth pinning is the exit code on each path, since
    that is what a task or a deploy gate reads.
    """

    def test_a_reachable_database_exits_zero(self, monkeypatch):
        monkeypatch.setattr(
            "agent_app.one.api.one.engine",
            _FakeEngine(answer=1),
            raising=False,
        )
        with pytest.raises(SystemExit) as exc:
            cli.Cli().test_db_conn()
        assert exc.value.code == 0

    def test_an_unreachable_database_exits_one(self, monkeypatch):
        monkeypatch.setattr(
            "agent_app.one.api.one.engine",
            _FakeEngine(error=OSError("no route to host")),
            raising=False,
        )
        with pytest.raises(SystemExit) as exc:
            cli.Cli().test_db_conn()
        assert exc.value.code == 1


class _FakeConnection:
    def __init__(self, answer=None, error=None):
        self._answer = answer
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, statement):
        if self._error is not None:
            raise self._error
        return self

    def scalar_one(self):
        return self._answer


class _FakeEngine:
    def __init__(self, answer=None, error=None):
        self._answer = answer
        self._error = error

    def connect(self):
        return _FakeConnection(answer=self._answer, error=self._error)


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.cli",
        preview=False,
    )


class TestSnowflakeSync:
    def test_missing_settings_fail_before_any_connection(self, monkeypatch, capsys):
        def refuse(*args, **kwargs):
            raise ValueError("Set these in .env first (see .env.example): SNOWFLAKE_ADMIN_USER")

        def never(**kwargs):  # pragma: no cover - the point is that it is not reached
            raise AssertionError("run() must not be called")

        monkeypatch.setattr("agent_app.warehouse.snowflake_sync.settings_from_env", refuse)
        monkeypatch.setattr("agent_app.warehouse.snowflake_sync.run", never)
        with pytest.raises(SystemExit) as exc:
            cli.Cli().snowflake_sync()
        assert exc.value.code == 1
        assert "SNOWFLAKE_ADMIN_USER" in capsys.readouterr().out

    def test_the_exit_code_is_the_sync_result(self, monkeypatch):
        from agent_app.warehouse import snowflake_sync

        settings = snowflake_sync.SyncSettings(
            account="acme-test",
            admin_user="ME",
            objects=snowflake_sync.ddl.SnowflakeObjects("ACME", "ACME_WH", "ACME_READER", "ACME_SVC", "ACME_WH_MONITOR"),
            path_private_key=snowflake_sync.DEFAULT_PATH_PRIVATE_KEY,
            credit_quota=2,
        )
        seen = {}

        def fake_run(**kwargs):
            seen.update(kwargs)
            return 0

        monkeypatch.setattr("agent_app.warehouse.snowflake_sync.settings_from_env", lambda *a: settings)
        monkeypatch.setattr("agent_app.warehouse.snowflake_sync.admin_private_key_der", lambda: b"der")
        monkeypatch.setattr("agent_app.warehouse.snowflake_sync.run", fake_run)
        with pytest.raises(SystemExit) as exc:
            cli.Cli().snowflake_sync()
        assert exc.value.code == 0
        assert seen["objects"].monitor == "ACME_WH_MONITOR"
        assert seen["path_duckdb"].suffix == ".duckdb"


class TestSnowflakeAdminKey:
    def test_needs_the_admin_user(self, monkeypatch, capsys):
        monkeypatch.setattr("agent_app.config.get_env", lambda name: None)
        with pytest.raises(SystemExit) as exc:
            cli.Cli().snowflake_admin_key()
        assert exc.value.code == 1
        assert "SNOWFLAKE_ADMIN_USER" in capsys.readouterr().out

    def test_prints_the_alter_user(self, monkeypatch, capsys, tmp_path):
        from agent_app.warehouse import snowflake_sync

        monkeypatch.setattr("agent_app.config.get_env", lambda name: "ME")
        monkeypatch.setattr(snowflake_sync, "DEFAULT_PATH_ADMIN_KEY", tmp_path / "admin.pem")
        with pytest.raises(SystemExit) as exc:
            cli.Cli().snowflake_admin_key()
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "ALTER USER ME SET RSA_PUBLIC_KEY = 'MII" in out
        assert "PRIVATE KEY" not in out
        assert (tmp_path / "admin.pem").is_file()
