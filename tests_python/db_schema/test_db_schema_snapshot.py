# -*- coding: utf-8 -*-

"""
The build-time schema snapshot: its file format and when a shipped one is used.
"""

import json

import pytest

from agent_app.db_schema.snapshot import SNAPSHOT_FORMAT
from agent_app.db_schema.snapshot import SchemaSnapshot
from agent_app.db_schema.snapshot import load_snapshot
from agent_app.db_schema.snapshot import write_snapshot


def acme_snapshot(**overrides) -> SchemaSnapshot:
    fields = dict(
        schema_name="acme_widgets",
        warehouse_engine="snowflake",
        schema_str="snowflake Database acme_widgets(...)",
        table_columns={"widget": frozenset({"widget_id", "name"}), "v_today": frozenset({"today"})},
    )
    return SchemaSnapshot(**{**fields, **overrides})


class TestFormat:
    def test_round_trip(self):
        snapshot = acme_snapshot()
        assert SchemaSnapshot.from_json(snapshot.to_json()) == snapshot

    def test_the_file_is_stable_and_readable(self):
        """Sorted, so two snapshots of one schema are byte-identical."""
        data = json.loads(acme_snapshot().to_json())
        assert data["format"] == SNAPSHOT_FORMAT
        assert list(data["table_columns"]) == ["v_today", "widget"]
        assert data["table_columns"]["widget"] == ["name", "widget_id"]

    @pytest.mark.parametrize(
        "text, reason",
        [
            ("not json", "not JSON"),
            ("[]", "not a format"),
            (json.dumps({"format": 999}), "not a format"),
            (json.dumps({"format": SNAPSHOT_FORMAT}), "incomplete"),
            (
                json.dumps(
                    {"format": SNAPSHOT_FORMAT, "schema_name": "a", "warehouse_engine": "duckdb",
                     "schema_str": "s", "table_columns": ["widget"]}
                ),
                "incomplete",
            ),
            (
                json.dumps(
                    {"format": SNAPSHOT_FORMAT, "schema_name": "a", "warehouse_engine": "duckdb",
                     "schema_str": "", "table_columns": {}}
                ),
                "empty",
            ),
        ],
    )
    def test_anything_else_is_refused(self, text, reason):
        with pytest.raises(ValueError, match=reason):
            SchemaSnapshot.from_json(text)


class TestLoad:
    def test_no_file_means_no_snapshot(self, tmp_path):
        assert load_snapshot(tmp_path / "missing.json", "acme_widgets", "snowflake") is None

    def test_a_matching_snapshot_is_used(self, tmp_path):
        path = tmp_path / "schema-snapshot.json"
        write_snapshot(path, acme_snapshot())
        assert load_snapshot(path, "acme_widgets", "snowflake") == acme_snapshot()

    @pytest.mark.parametrize("schema_name, engine", [("other_schema", "snowflake"), ("acme_widgets", "duckdb")])
    def test_a_snapshot_of_another_schema_or_engine_is_ignored(self, tmp_path, caplog, schema_name, engine):
        path = tmp_path / "schema-snapshot.json"
        write_snapshot(path, acme_snapshot())
        assert load_snapshot(path, schema_name, engine) is None
        assert "Ignoring schema snapshot" in caplog.text

    def test_a_broken_file_is_ignored_not_raised(self, tmp_path, caplog):
        path = tmp_path / "schema-snapshot.json"
        path.write_text("{", encoding="utf-8")
        assert load_snapshot(path, "acme_widgets", "snowflake") is None
        assert "not JSON" in caplog.text


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.db_schema.snapshot",
        preview=False,
    )
