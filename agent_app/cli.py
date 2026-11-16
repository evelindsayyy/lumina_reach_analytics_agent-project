# -*- coding: utf-8 -*-

"""
The application's command line: ``agent-app <command>``.

Installed as a console script by ``pyproject.toml``, so ``mise.toml`` names a
command rather than a file path. That indirection is the point: where a check
happens to live can change without every task, doc, and habit changing with it.

**Only application commands belong here**, building the local warehouse file
included: in this repo the dataset is part of the app, not a lesson.

Argument parsing only; the work lives in the module each command calls. The
parsing itself is ``fire``, which derives the interface from :class:`Cli` --
one public method is one subcommand, and its signature is that subcommand's
options. Adding a command is adding a method, with no parser wiring to keep in
step with it.

``fire`` accepts either spelling of a method name, so ``check-content`` and
``check_content`` both work; the hyphenated one is what the docs and tasks use.

    agent-app check-content
    agent-app check-content --retired "patient,bed,ward"
    agent-app test-db-conn
    agent-app ac-gen
    agent-app snowflake-admin-key
    agent-app snowflake-sync
    agent-app print-db-schema
"""

import typing as T

import fire


def _as_word_list(value: T.Any) -> list[str]:
    """
    Normalize whatever ``fire`` handed us into a list of non-empty words.

    ``--retired "a,b"`` arrives as a tuple because fire parses comma-separated
    values for us, but ``--retired a`` arrives as a plain string and
    ``--retired ""`` as an empty one. Accepting all three keeps the flag's
    behaviour independent of how many words happen to be in it.
    """
    if not value:
        return []
    if isinstance(value, str):
        value = value.split(",")
    return [str(word).strip() for word in value if str(word).strip()]


def _put_secure_string(name: str, value: str | None, missing_hint: str) -> None:
    """
    Write ``value`` to the SSM SecureString ``name`` if it changed, and exit.
    The value is never printed, and it is compared after decryption, so a
    rerun with the same secret writes nothing.
    """
    from agent_app.api import one

    if not value:
        print(f"FAILED: {missing_hint}")
        raise SystemExit(1)
    ssm = one.boto_ses.client("ssm")
    try:
        current = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        current = None
    if current == value:
        print(f"Unchanged: SSM parameter {name}")
        raise SystemExit(0)
    ssm.put_parameter(Name=name, Value=value, Type="SecureString", Overwrite=True)
    print(f"{'Updated' if current else 'Created'}: SSM SecureString {name}")
    raise SystemExit(0)


class Cli:
    """
    Application commands. One public method is one subcommand.

    Every command exits through :class:`SystemExit` rather than returning a
    code, because fire prints a returned value and then exits 0 -- which would
    turn a failed check into a green build with the number 1 on stdout.
    """

    def check_content(self, retired: T.Any = "") -> None:
        """
        Verify data/ still agrees with the prompt, the seed, and itself.

        :param retired: Vocabulary from the dataset this repo used to serve,
            comma-separated. Pass it right after a swap to prove none of it
            survives, e.g. ``--retired "patient,bed,ward"``. Empty by default.
        """
        from agent_app.content_check import run

        raise SystemExit(run(retired=_as_word_list(retired)))

    def gen_data(self, seed: int = 42) -> None:
        """
        Build the local warehouse file by running the dataset's generator.

        The generator is ``dataset/04-*generator*.py``, discovered rather than
        named so that a dataset swap never edits this package. It replaces any
        ``.duckdb`` file already in ``dataset/``.
        """
        import subprocess

        from agent_app.paths import path_enum
        from agent_app.warehouse.engines import DIR_DATASET

        generators = sorted(DIR_DATASET.glob("04-*generator*.py"))
        if len(generators) != 1:
            print(f"FAILED: expected one 04-*generator*.py in {DIR_DATASET}, found {len(generators)}")
            raise SystemExit(1)
        for old in DIR_DATASET.glob("*.duckdb"):
            old.unlink()
        argv = [str(path_enum.path_venv_python), str(generators[0]), "--seed", str(seed)]
        raise SystemExit(subprocess.run(argv, cwd=path_enum.dir_project_root, check=False).returncode)

    def test_db_conn(self) -> None:
        """
        Prove this machine can reach the configured warehouse, and nothing else.

        The smallest possible round trip: connect, ``SELECT 1``, disconnect. It
        touches no table on purpose -- when the agent is not working, this
        separates a credential or network problem from an empty schema, which
        are the two failures that otherwise look alike.
        """
        import sqlalchemy as sa

        from agent_app.api import one

        print(f"Connecting to the {one.config.warehouse_engine} warehouse ...")
        try:
            with one.engine.connect() as conn:
                value = conn.execute(sa.text("SELECT 1")).scalar_one()
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
            print(
                "\nLocally, build the DuckDB file with `mise run gen-data`. For "
                "Snowflake, check the SNOWFLAKE_* variables in .env -- see "
                ".env.example for the full list."
            )
            raise SystemExit(1)

        print(f"OK: the warehouse answered {value}.")
        raise SystemExit(0)

    def snowflake_admin_key(self) -> None:
        """
        Create your own key pair for the sync (reused if it exists) and print
        the ``ALTER USER`` to run once in a Snowsight worksheet. Writes only
        to ``tmp/snowflake/``; the public key it prints is not a secret.
        """
        from agent_app.config import get_env, load_env_files
        from agent_app.warehouse import snowflake_sync

        # nothing here builds `one.config`, which is what loads .env elsewhere
        load_env_files()
        admin_user = get_env("SNOWFLAKE_ADMIN_USER")
        if not admin_user:
            print("FAILED: set SNOWFLAKE_ADMIN_USER in .env first (see .env.example)")
            raise SystemExit(1)
        keys = snowflake_sync.load_or_create_key_pair(snowflake_sync.DEFAULT_PATH_ADMIN_KEY)
        verb = "Created" if keys.created else "Reusing"
        print(f"{verb} your private key: {keys.path_private_key} (git-ignored, keep it private)\n")
        print("Run this once in a Snowsight worksheet, signed in as yourself:\n")
        print(snowflake_sync.render_admin_key_sql(admin_user, keys.public_key_body))
        raise SystemExit(0)

    def snowflake_sync(self) -> None:
        """
        Copy the local DuckDB warehouse into Snowflake, signed in as you with
        your key pair from ``snowflake-admin-key`` (writes to Snowflake).

        Sets up the account first (an X-Small warehouse with a monthly credit
        cap, the read-only role, the key-pair service user), then rebuilds the
        schema, loads every table and checks each row count. Safe to rerun:
        the schema is replaced, and an existing key pair is reused.
        """
        from agent_app.config import get_env, get_env_int
        from agent_app.api import one
        from agent_app.warehouse.engines import find_duckdb_file
        from agent_app.warehouse import snowflake_sync

        try:
            settings = snowflake_sync.settings_from_env(one.config, get_env, get_env_int)
            path_duckdb = find_duckdb_file()
            snowflake_sync.admin_private_key_der()
        except (ValueError, FileNotFoundError, RuntimeError) as e:
            print(f"FAILED: {e}")
            raise SystemExit(1)
        raise SystemExit(
            snowflake_sync.run(
                account=settings.account,
                admin_user=settings.admin_user,
                objects=settings.objects,
                schema=one.config.schema_name,
                path_duckdb=path_duckdb,
                path_private_key=settings.path_private_key,
                credit_quota=settings.credit_quota,
            )
        )

    def ac_gen(self, teardown: bool = False) -> None:
        """
        Write the AgentCore project (``agentcore/agentcore.json``,
        ``aws-targets.json``, ``app-config.json``) and each runtime's CodeZip
        directory (``build/agentcore/``). Reads the AWS account of your
        credentials (one read-only STS call); writes nothing to AWS.

        :param teardown: write an empty project instead, whose deploy destroys
            the stack.
        """
        import boto3

        from agent_app.api import one
        from agent_app.config import get_env
        from agent_app.agentcore_project import codezip, gen
        from agent_app.agentcore_project.settings import deploy_settings_from_env

        try:
            account_id = boto3.Session(region_name=one.config.aws_region).client("sts").get_caller_identity()["Account"]
            settings = deploy_settings_from_env(one.config, get_env, account_id)
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
            raise SystemExit(1)
        if teardown:
            gen.generate_teardown(settings)
        else:
            gen.generate_all(settings, codezip.export_requirements())
        raise SystemExit(0)

    def test_deployed(self, question: str = "") -> None:
        """
        Ask the deployed agent one question with a Cognito token, and check a
        call without one is refused (creates a test user on the first run).
        """
        from agent_app.agentcore_project import deployed_check

        raise SystemExit(deployed_check.run(question or deployed_check.DEFAULT_QUESTION))

    def ac_check_wheels(self) -> None:
        """
        Check each runtime's dependencies install the way ``agentcore deploy``
        installs them: wheels only, Linux aarch64 (a dry run, no AWS call).
        Run ``ac-gen`` first.
        """
        from agent_app.agentcore_project import codezip
        from agent_app.agentcore_project.settings import DIR_CODEZIP

        paths = sorted(DIR_CODEZIP.glob("*/pyproject.toml"))
        if not paths:
            print("FAILED: no runtime in build/agentcore/; run `mise run ac-gen` first")
            raise SystemExit(1)
        failed = False
        for path in paths:
            error = codezip.check_codezip_install(path)
            print(f"OK: {path.parent.name}" if error is None else f"FAILED: {path.parent.name}\n{error}")
            failed = failed or error is not None
        raise SystemExit(1 if failed else 0)

    def snowflake_key_deploy(self) -> None:
        """
        Write the Snowflake service user's private key to its SSM SecureString,
        which only the MCP runtime's role may read (writes to AWS).
        """
        from agent_app.api import one
        from agent_app.agentcore_project.settings import SNOWFLAKE_KEY_PARAM_NAME

        _put_secure_string(
            SNOWFLAKE_KEY_PARAM_NAME,
            one.config.snowflake_private_key_pem,
            "no Snowflake private key; set SNOWFLAKE_PRIVATE_KEY_PATH in .env",
        )

    def anthropic_key_deploy(self) -> None:
        """
        Write the Anthropic API key from .env to its SSM SecureString, which
        only the agent runtime's role may read (writes to AWS).
        """
        from agent_app.api import one
        from agent_app.agentcore_project.settings import ANTHROPIC_KEY_PARAM_NAME

        _put_secure_string(
            ANTHROPIC_KEY_PARAM_NAME,
            one.config.anthropic_api_key,
            "no Anthropic API key; set ANTHROPIC_API_KEY in .env",
        )

    def print_db_schema(self) -> None:
        """
        Print the database schema exactly as the agent is shown it.

        Not a dump of the database: it is the compact encoding the agent reads
        as its entire picture of the tables, so this is the one way to see what
        the model actually knows before it writes a line of SQL. Reads this
        project's schema only, and needs a built one -- an empty schema raises
        rather than printing nothing, because nothing is what an unbuilt
        warehouse and a broken encoder both look like.
        """
        from agent_app.api import one

        print(one.database_schema_str)
        raise SystemExit(0)


def main() -> None:
    fire.Fire(Cli, name="agent-app")


if __name__ == "__main__":
    main()
