# -*- coding: utf-8 -*-

"""
The two engines the agent can read, both behind SQLAlchemy so that schema
reflection and the always-rolled-back transaction of
:func:`agent_app.sql_utils.execute_sql_query` work the same on either:

- **DuckDB**, a local file built by the dataset's generator. Development,
  tests and evaluation run on it, with no account and no network.
- **Snowflake**, the deployed warehouse. A service user with key-pair auth
  (no password exists) and a role holding only ``USAGE`` and ``SELECT``.

SQL is written in the Snowflake dialect everywhere. On DuckDB it is transpiled
with sqlglot just before it runs (see :mod:`.dialect`), so the prompt, the
guardrails and the golden queries are written once.

Both are read-only below the guardrails: the DuckDB file is opened
``read_only``, and the Snowflake role cannot write.
"""

import dataclasses
from pathlib import Path

import sqlalchemy as sa

from ..paths import path_enum

#: Where the dataset's generator writes its file. Discovered, not named, so a
#: dataset swap never edits this package.
DIR_DATASET = path_enum.dir_project_root / "dataset"

#: How to build the file, quoted by the errors that need it.
GEN_HINT = "mise run gen-data"


def find_duckdb_file(dir_dataset: Path = DIR_DATASET) -> Path:
    """
    The single ``.duckdb`` file in ``dir_dataset``.

    :raises FileNotFoundError: none was built yet.
    :raises RuntimeError: more than one; picking one silently is how the wrong
        dataset gets served.
    """
    found = sorted(dir_dataset.glob("*.duckdb"))
    if not found:
        raise FileNotFoundError(f"No .duckdb file in {dir_dataset}. Build it with `{GEN_HINT}`.")
    if len(found) > 1:
        names = ", ".join(p.name for p in found)
        raise RuntimeError(f"{dir_dataset} holds more than one .duckdb file: {names}. Delete the ones you are not using.")
    return found[0]


def new_duckdb_engine(path: Path, schema_name: str) -> sa.Engine:
    """
    A read-only engine on the DuckDB file, with ``schema_name`` as the default
    schema, so the agent writes ``FROM campaign`` and it resolves.

    ``search_path`` is set on every new DBAPI connection: DuckDB has no pooling
    proxy in between, so the setting stays with the connection that runs the
    query (the reason the Postgres version needed ``SET LOCAL`` does not apply).
    """
    if Path(path).stem.lower() == schema_name.lower():
        raise ValueError(
            f"{Path(path).name} would make {schema_name!r} ambiguous: DuckDB names "
            f"the catalog after the file, so a file named like its schema breaks "
            f"every qualified reference. Rename the file."
        )
    engine = sa.create_engine(f"duckdb:///{path}", connect_args={"read_only": True})
    quoted = schema_name.replace("'", "''")

    @sa.event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection, _):
        dbapi_connection.execute(f"SET search_path = '{quoted}'")

    return engine


@dataclasses.dataclass(frozen=True)
class SnowflakeSettings:
    """
    Where and as whom to connect to Snowflake.
    """

    # fmt: off
    account: str = dataclasses.field()  #: Account identifier, such as ``myorg-myaccount``.
    user: str = dataclasses.field()  #: The agent's service user.
    role: str = dataclasses.field()  #: Its read-only role.
    warehouse: str = dataclasses.field()  #: Virtual warehouse to run on.
    database: str = dataclasses.field()  #: The database holding the schema.
    private_key_pem: str = dataclasses.field(repr=False)  #: PKCS8 PEM private key (key-pair auth, no password).
    # fmt: on

    def missing(self) -> list[str]:
        """
        Names of the settings that are empty.
        """
        return [field.name for field in dataclasses.fields(self) if not getattr(self, field.name)]


def private_key_der(private_key_pem: str) -> bytes:
    """
    The PEM private key as the DER bytes the Snowflake connector takes.
    """
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def new_snowflake_engine(settings: SnowflakeSettings, schema_name: str) -> sa.Engine:
    """
    An engine on the Snowflake schema ``schema_name``, as the service user.

    :raises ValueError: a setting is missing, named in the message, rather
        than a connector error several layers away on the first query.
    """
    missing = settings.missing()
    if missing:
        names = ", ".join(f"SNOWFLAKE_{name.upper()}" for name in missing)
        raise ValueError(f"WAREHOUSE_ENGINE is 'snowflake' but these are not set: {names}")
    from snowflake.sqlalchemy import URL

    url = URL(
        account=settings.account,
        user=settings.user,
        role=settings.role,
        warehouse=settings.warehouse,
        database=settings.database,
        schema=schema_name,
    )
    return sa.create_engine(url, connect_args={"private_key": private_key_der(settings.private_key_pem)})
