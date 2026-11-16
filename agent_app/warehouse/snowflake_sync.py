# -*- coding: utf-8 -*-

"""
Copy the local DuckDB warehouse into Snowflake: ``agent-app snowflake-sync``.

1. The service user's key pair: reused from ``tmp/snowflake/`` (git-ignored)
   when it exists, so a re-sync never invalidates a deployed key; created when
   it does not.
2. The account setup and the schema rebuild of :mod:`.snowflake_ddl`.
3. The data: Parquet out of DuckDB, ``PUT`` + ``COPY INTO`` each table.
4. A row count of every table on both sides; any difference fails the sync.

It runs as you, with a key pair of your own (``agent-app snowflake-admin-key``
creates it and prints the one ``ALTER USER`` you paste into a Snowsight
worksheet). No password is ever typed into, read by or stored by this code,
and the agent's user has none at all. Browser sign-in
(``externalbrowser``) is not used: it needs a SAML identity provider, which a
fresh account does not have.
"""

import dataclasses
import tempfile
from pathlib import Path

from ..paths import path_enum
from . import snowflake_ddl as ddl

#: Where the service user's private key lives unless SNOWFLAKE_PRIVATE_KEY_PATH
#: says otherwise. ``tmp/`` is git-ignored.
DEFAULT_PATH_PRIVATE_KEY = path_enum.dir_project_root / "tmp" / "snowflake" / "agent_svc_private_key.pem"

#: Your own (the admin's) private key, used only by the sync. Remove it from
#: Snowflake with ``ALTER USER <you> UNSET RSA_PUBLIC_KEY`` when you are done.
DEFAULT_PATH_ADMIN_KEY = path_enum.dir_project_root / "tmp" / "snowflake" / "admin_private_key.pem"

#: The monthly credit cap when SNOWFLAKE_MONTHLY_CREDIT_QUOTA is unset.
DEFAULT_CREDIT_QUOTA = 2


@dataclasses.dataclass(frozen=True)
class KeyPair:
    path_private_key: Path
    public_key_body: str  #: PEM without the BEGIN / END lines and newlines.
    created: bool


def public_key_body(private_key) -> str:
    """
    The public half of ``private_key`` the way ``RSA_PUBLIC_KEY`` takes it.
    """
    from cryptography.hazmat.primitives import serialization

    pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return "".join(line for line in pem.splitlines() if "-----" not in line)


def load_or_create_key_pair(path: Path = DEFAULT_PATH_PRIVATE_KEY) -> KeyPair:
    """
    The key pair whose private key is at ``path``; a new 2048-bit RSA one,
    written there as an unencrypted PKCS8 PEM with mode 600, if none is.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    path = Path(path)
    if path.is_file():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        return KeyPair(path, public_key_body(key), created=False)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    return KeyPair(path, public_key_body(key), created=True)


def render_admin_key_sql(admin_user: str, public_key_body: str) -> str:
    """
    The statement you run once in Snowsight, signed in as yourself, so the
    sync can sign in as you with the key pair instead of a password.
    """
    return f"ALTER USER {admin_user} SET RSA_PUBLIC_KEY = '{public_key_body}';"


def admin_private_key_der(path: Path = DEFAULT_PATH_ADMIN_KEY) -> bytes:
    """
    Your private key as the DER bytes the connector takes.

    :raises FileNotFoundError: there is none yet, with the command that makes it.
    """
    from .engines import private_key_der

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f"No admin key at {path}. Run `mise run wh-snowflake-admin-key` and "
            f"paste the ALTER USER it prints into a Snowsight worksheet first."
        )
    return private_key_der(path.read_text(encoding="utf-8"))


def count_differences(expected: dict[str, int], actual: dict[str, int]) -> list[str]:
    """
    One line per table whose row count in Snowflake is not DuckDB's.
    """
    return [
        f"{table}: DuckDB {n:,} rows, Snowflake {actual.get(table, 0):,}"
        for table, n in expected.items()
        if actual.get(table) != n
    ]


def run(
    account: str,
    admin_user: str,
    objects: ddl.SnowflakeObjects,
    schema: str,
    path_duckdb: Path,
    path_private_key: Path,
    credit_quota: int,
) -> int:  # pragma: no cover - needs a Snowflake account
    """
    Every step, against the account. Returns the exit code.
    """
    import duckdb
    import snowflake.connector

    admin_key = admin_private_key_der()
    keys = load_or_create_key_pair(path_private_key)
    verb = "Created" if keys.created else "Reusing"
    print(f"{verb} the private key of {objects.user}: {keys.path_private_key} (git-ignored)")

    source = duckdb.connect(str(path_duckdb), read_only=True)
    connection = snowflake.connector.connect(
        account=account, user=admin_user, authenticator="SNOWFLAKE_JWT", private_key=admin_key
    )
    try:
        catalog = ddl.read_catalog(source, schema)
        cursor = connection.cursor()
        statements = ddl.render_account_sql(objects, schema, keys.public_key_body, credit_quota)
        statements += ["USE ROLE SYSADMIN", f"USE DATABASE {objects.database}", f"USE WAREHOUSE {objects.warehouse}"]
        statements += ddl.render_schema_sql(catalog, schema)
        for statement in statements:
            cursor.execute(statement)
        print(f"Built {objects.database}.{schema}: {len(catalog.tables)} tables, {len(catalog.views)} views")

        with tempfile.TemporaryDirectory() as dir_tmp:
            for path in ddl.export_parquet(source, catalog, schema, Path(dir_tmp)):
                for statement in ddl.render_load_sql(path, schema, path.stem):
                    cursor.execute(statement)
        for statement in ddl.render_read_grants(objects, schema):
            cursor.execute(statement)

        cursor.execute("USE ROLE SYSADMIN")
        expected, actual = {}, {}
        for table in catalog.tables:
            expected[table.name] = source.execute(f'SELECT count(*) FROM {schema}."{table.name}"').fetchone()[0]
            actual[table.name] = cursor.execute(f"SELECT COUNT(*) FROM {schema}.{table.name}").fetchone()[0]
    finally:
        connection.close()
        source.close()

    differences = count_differences(expected, actual)
    if differences:
        print("FAILED: row counts differ\n  " + "\n  ".join(differences))
        return 1
    print(f"OK: {sum(actual.values()):,} rows in {len(actual)} tables, every count matches DuckDB.")
    print(
        f"Monthly cap: {credit_quota} credits on {objects.warehouse} (resource monitor {objects.monitor}).\n"
        f"Next: set WAREHOUSE_ENGINE=\"snowflake\" in .env and run `mise run cli-test-db-conn`, "
        f"which connects as {objects.user} with the key pair."
    )
    return 0


@dataclasses.dataclass(frozen=True)
class SyncSettings:
    """
    Everything :func:`run` needs, read from the environment.
    """

    account: str
    admin_user: str
    objects: ddl.SnowflakeObjects
    path_private_key: Path
    credit_quota: int


def settings_from_env(config, get_env, get_env_int) -> SyncSettings:
    """
    The sync's settings: the agent's object names from ``config`` (the same
    ``SNOWFLAKE_*`` variables the agent connects with), plus
    ``SNOWFLAKE_ADMIN_USER`` (you), ``SNOWFLAKE_MONTHLY_CREDIT_QUOTA`` and
    ``SNOWFLAKE_PRIVATE_KEY_PATH``.

    :raises ValueError: naming every variable that is missing.
    """
    values = {
        "SNOWFLAKE_ACCOUNT": config.snowflake_account,
        "SNOWFLAKE_ADMIN_USER": get_env("SNOWFLAKE_ADMIN_USER"),
        "SNOWFLAKE_USER": config.snowflake_user,
        "SNOWFLAKE_ROLE": config.snowflake_role,
        "SNOWFLAKE_WAREHOUSE": config.snowflake_warehouse,
        "SNOWFLAKE_DATABASE": config.snowflake_database,
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"Set these in .env first (see .env.example): {', '.join(missing)}")
    warehouse = values["SNOWFLAKE_WAREHOUSE"]
    quota = get_env_int("SNOWFLAKE_MONTHLY_CREDIT_QUOTA")
    path = get_env("SNOWFLAKE_PRIVATE_KEY_PATH")
    return SyncSettings(
        account=values["SNOWFLAKE_ACCOUNT"],
        admin_user=values["SNOWFLAKE_ADMIN_USER"],
        objects=ddl.SnowflakeObjects(
            database=values["SNOWFLAKE_DATABASE"],
            warehouse=warehouse,
            role=values["SNOWFLAKE_ROLE"],
            user=values["SNOWFLAKE_USER"],
            monitor=f"{warehouse}_MONITOR",
        ),
        path_private_key=Path(path).expanduser() if path else DEFAULT_PATH_PRIVATE_KEY,
        credit_quota=DEFAULT_CREDIT_QUOTA if quota is None else quota,
    )
