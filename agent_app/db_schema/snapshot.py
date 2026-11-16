# -*- coding: utf-8 -*-

"""
A build-time copy of what schema reflection gives the agent: the encoded
schema it reads, and the table -> columns allowlist of the SQL guardrails.

Why it exists: on Snowflake, reflecting the schema takes about 30 s, and a cold
MCP runtime pays it before the first question can be answered. The deploy
takes the snapshot once (``agent-app ac-gen``) and ships it inside the MCP
runtime's CodeZip, so a cold start reads a file instead.

A snapshot is used only when it was taken of the same schema on the same
engine; any other file, or one that cannot be read, falls back to live
reflection. It goes stale when the warehouse schema changes, so redeploy after
``mise run wh-snowflake-sync``.
"""

import dataclasses
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: Bumped when the file layout changes; any other version is ignored.
SNAPSHOT_FORMAT = 1


@dataclasses.dataclass(frozen=True)
class SchemaSnapshot:
    """
    The schema of ``schema_name`` on ``warehouse_engine``, as reflected.
    """

    # fmt: off
    schema_name: str = dataclasses.field()
    warehouse_engine: str = dataclasses.field()
    schema_str: str = dataclasses.field()  #: What ``get_database_schema`` returns.
    table_columns: dict[str, frozenset[str]] = dataclasses.field()  #: Lower-case table -> column names.
    # fmt: on

    def to_json(self) -> str:
        """Sorted, so two snapshots of one schema are byte-identical."""
        data = {
            "format": SNAPSHOT_FORMAT,
            "schema_name": self.schema_name,
            "warehouse_engine": self.warehouse_engine,
            "schema_str": self.schema_str,
            "table_columns": {table: sorted(columns) for table, columns in sorted(self.table_columns.items())},
        }
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "SchemaSnapshot":
        """
        :raises ValueError: when ``text`` is not a complete snapshot of this format.
        """
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"not JSON: {e}") from e
        if not isinstance(data, dict) or data.get("format") != SNAPSHOT_FORMAT:
            raise ValueError(f"not a format-{SNAPSHOT_FORMAT} schema snapshot")
        try:
            snapshot = cls(
                schema_name=str(data["schema_name"]),
                warehouse_engine=str(data["warehouse_engine"]),
                schema_str=str(data["schema_str"]),
                table_columns={
                    str(table): frozenset(str(column) for column in columns)
                    for table, columns in data["table_columns"].items()
                },
            )
        except (KeyError, AttributeError, TypeError) as e:
            raise ValueError(f"incomplete schema snapshot: {e!r}") from e
        if not snapshot.schema_str or not snapshot.table_columns:
            raise ValueError("empty schema snapshot")
        return snapshot


def write_snapshot(path: Path, snapshot: SchemaSnapshot) -> None:
    path.write_text(snapshot.to_json(), encoding="utf-8")


def load_snapshot(path: Path, schema_name: str, warehouse_engine: str) -> SchemaSnapshot | None:
    """
    The snapshot at ``path`` if it is one of ``schema_name`` on
    ``warehouse_engine``, else None. No file is the normal local case and is
    silent; a file that is not used says why.
    """
    if not path.exists():
        return None
    try:
        snapshot = SchemaSnapshot.from_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning(f"Ignoring schema snapshot {path}: {e}")
        return None
    if (snapshot.schema_name, snapshot.warehouse_engine) != (schema_name, warehouse_engine):
        logger.warning(
            f"Ignoring schema snapshot {path}: taken of {snapshot.schema_name!r} on "
            f"{snapshot.warehouse_engine}, not {schema_name!r} on {warehouse_engine}"
        )
        return None
    return snapshot
