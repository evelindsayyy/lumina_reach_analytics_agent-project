# -*- coding: utf-8 -*-

"""
Does the repo still agree with the content in ``data/``?

Every check here compares two things a dataset swap must keep in agreement, and
fails the build when they disagree. Hand-rewritten prose cannot be type-checked,
so the failures this catches are the silent kind: a prompt that queries a table
the previous dataset left behind, a kickstart button whose icon promises a chart
over a paragraph of prose. Nothing crashes. The app simply lies.

Two of the checks need the local DuckDB warehouse file that ``mise run gen-data``
builds -- see :func:`seed_tables`.

Icon names and required ``site.toml`` keys are deliberately **not** checked here.
``lib/site/load.ts`` checks them against ``lib/icons.ts`` when Next.js reads the
TOML, which is a real check at build time rather than a second list to keep in
step. That is what ``mise run build-web`` is for.
"""

import re
import tomllib
import typing as T
from pathlib import Path

import sqlalchemy as sa

from agent_app.paths import path_enum


#: Directories worth scanning for retired vocabulary: everything that is code or
#: config. Prose is deliberately excluded -- ``docs/`` and ``blogs/`` legitimately
#: discuss past datasets, and failing on a tutorial that explains the previous
#: domain would train the reader to ignore this script.
SCAN_DIRS = [
    "app",
    "components",
    "lib",
    "data",
    "types",
    "api",
    "agent_app",
    "scripts",
    "tests_python",
    "config",
]

#: File extensions worth scanning inside :data:`SCAN_DIRS`.
#:
#: ``.toml`` earns its place twice over: ``data/site.toml`` holds every sentence
#: the UI says, which makes it the densest concentration of the outgoing domain's
#: vocabulary in the repo, and therefore the one file this scan most needs to
#: read.
SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".sql", ".toml"}

#: Files exempt from the retired-vocabulary scan, because listing those words is
#: precisely their job.
SCAN_EXEMPT = {
    "agent_app/content_check.py",
    # Its --retired help text spells out an example word list.
    "agent_app/cli.py",
}

#: Identifiers that can follow FROM/JOIN in the system prompt without naming a
#: real table: SQL keywords, and the generic stand-ins a prompt uses when it is
#: illustrating a shape rather than a query ("... FROM table").
PROMPT_NON_TABLES = {
    "select",
    "lateral",
    "unnest",
    "values",
    "table",
    "table_name",
    "your_table",
}

#: How many kickstart questions of each kind ``data/site.toml`` must carry.
#:
#: Twelve buttons that all return prose leave the diagram renderer and the chart
#: renderer with nothing to draw, which is the same as not having built them.
RENDER_QUOTAS = {"table": 3, "flowchart": 3, "chart": 3, "free": 3}

#: The phrase that actually makes each block appear.
#:
#: The other half of the contract in the prompt's ``## Rendering Triggers``
#: table. The model follows the wording, not the intent, so these are literal.
RENDER_PHRASES = {
    "table": (("as a markdown table",), ("show the sql",)),
    "flowchart": (("as a flowchart", "as a diagram"),),
    "chart": (("as a bar chart", "as a line chart"),),
}



class Report:
    """
    Accumulates findings so that one run reports *every* problem, not just the
    first.

    A checker that stops at the first failure turns a swap into a slow
    fix-one-rerun loop. Collecting everything means one run gives you the whole
    list of what still needs doing.
    """

    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, check: str, message: str):
        self.errors.append(f"[{check}] {message}")

    def warn(self, check: str, message: str):
        self.warnings.append(f"[{check}] {message}")

    def section(self, title: str, ok: bool | None):
        """``ok=None`` prints SKIP, for a check that could not run at all."""
        mark = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        print(f"  {mark}  {title}")


def iter_scan_files() -> T.Iterator[Path]:
    """Yield every code/config file that the retired-vocabulary scan covers."""
    root = path_enum.dir_project_root
    for dir_name in SCAN_DIRS:
        directory = root / dir_name
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in SCAN_SUFFIXES:
                continue
            if "__pycache__" in path.parts or "node_modules" in path.parts:
                continue
            if str(path.relative_to(root)) in SCAN_EXEMPT:
                continue
            yield path


def check_retired_terms(report: Report, terms: list[str]) -> bool:
    """
    Fail if vocabulary from a retired dataset still appears in the code.

    Terms come from ``--retired``, not from a committed config file. This check
    is a *migration* tool: its value peaks the day you swap datasets and drops to
    zero once the swap is clean. Storing the previous domain's nouns in the repo
    forever puts words from a dead dataset in the current one's config, and the
    list rots silently whenever someone forgets to update it.

    Run it by hand right after a swap::

        mise run cli-check-content -- --retired "patient,bed,ward,nurse"

    Matching is whole-word and case-insensitive, so ``bed`` flags a stray
    hospital reference without flagging ``bedrock``.
    """
    if not terms:
        return True

    pattern = re.compile(
        r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b",
        re.IGNORECASE,
    )
    root = path_enum.dir_project_root
    hits = 0
    for path in iter_scan_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = pattern.search(line)
            if match:
                hits += 1
                report.error(
                    "retired-terms",
                    f"{path.relative_to(root)}:{lineno} still says "
                    f"{match.group(0)!r}, left over from a previous dataset.",
                )

    ok = hits == 0
    report.section(f"retired vocabulary ({len(terms)} terms)", ok)
    return ok


def _schema_name() -> str:
    """The dataset's schema, from the app's config."""
    from agent_app.api import one

    return one.config.schema_name


def _duckdb_file() -> Path:
    """The local warehouse file; raises when none was built."""
    from agent_app.warehouse.engines import find_duckdb_file

    return find_duckdb_file()


def seed_metadata() -> tuple[sa.MetaData | None, str | None]:
    """
    The local warehouse file's tables and views, reflected, plus a reason when
    there are none.

    Always the DuckDB file, whatever ``WAREHOUSE_ENGINE`` says: this checks the
    content against the dataset as generated, and must run with no account.
    """
    import warnings

    from agent_app.warehouse.engines import GEN_HINT, new_duckdb_engine

    try:
        path = _duckdb_file()
    except FileNotFoundError:
        return None, f"no warehouse file has been built yet. Build it with:\n         {GEN_HINT}"

    schema_name = _schema_name()
    engine = new_duckdb_engine(path, schema_name=schema_name)
    metadata = sa.MetaData(schema=schema_name)
    with warnings.catch_warnings():
        # duckdb-engine cannot reflect indexes yet and says so on every table
        warnings.simplefilter("ignore", category=Warning)
        metadata.reflect(bind=engine, schema=schema_name, views=True)
    engine.dispose()
    if not metadata.tables:
        return None, f"{path.name} holds no tables in schema {schema_name!r}. Rebuild it with:\n         {GEN_HINT}"
    return metadata, None


def seed_tables() -> tuple[set[str], str | None]:
    """
    The warehouse file's table and view names, plus a reason when there are none.
    """
    metadata, reason = seed_metadata()
    if metadata is None:
        return set(), reason
    return {table.name for table in metadata.tables.values()}, None


def check_table_insert_order(report: Report, metadata: sa.MetaData) -> bool:
    """
    Fail if the warehouse's foreign keys admit no insert order at all.

    The order itself is not configured -- loading Snowflake reads it off
    ``metadata.sorted_tables`` -- so there is no list left to disagree with the
    file. What can still go wrong is a foreign-key *cycle*: two tables that each
    require the other to exist first. SQLAlchemy only warns about it; this
    turns the warning into the failure it is.
    """
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", category=sa.exc.SAWarning)
        try:
            order = metadata.sorted_tables
        except sa.exc.SAWarning as e:
            report.error(
                "table-order",
                f"the warehouse's foreign keys form a cycle, so no insert order "
                f"can satisfy them: {e}",
            )
            report.section("table insert order (cycle)", False)
            return False

    report.section(f"table insert order ({len(order)} tables)", True)
    return True


def check_prompt_tables(report: Report, db_tables: set[str]) -> bool:
    """
    Fail if the system prompt queries a table the database does not have.

    Scans for identifiers following ``FROM`` and ``JOIN``, **inside ```sql
    fenced blocks only**. A prompt that teaches the agent to query a table left
    behind by the previous dataset produces confident, entirely wrong SQL at
    runtime.

    Scoping to the fenced blocks is what keeps this honest. Scanning the whole
    file cannot tell prose from SQL, and the prompt legitimately discusses SQL
    in prose: the dialect section says to write ``EXTRACT(QUARTER FROM d)``, and
    a whole-file scan reads that as a query against a table called ``d``.

    A dotted name is skipped too. ``EXTRACT(QUARTER FROM l.disbursement_date)``
    is a column reference that happens to follow ``FROM``.

    Names the prompt defines itself as CTEs (``WITH early_behavior AS (...)``)
    are resolved and excluded -- they read exactly like table references but are
    local to the query, so flagging them would be pure noise.
    """
    path = path_enum.path_bi_agent_system_prompt_md
    if not path.exists():
        report.error("prompt-tables", f"system prompt not found at {path}")
        report.section("prompt table references", False)
        return False

    text = path.read_text(encoding="utf-8")
    sql_blocks = "\n".join(re.findall(r"```sql\n(.*?)```", text, re.S))
    referenced = set(
        name.lower()
        for name in re.findall(
            # The trailing `(?!\.)` drops `FROM l.disbursement_date`, which is a
            # column inside EXTRACT rather than a table.
            r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)(?!\s*\.)",
            sql_blocks,
            re.IGNORECASE,
        )
    )

    # CTEs the prompt defines itself: `WITH name AS (` and `, name AS (`.
    cte_names = set(
        name.lower()
        for name in re.findall(
            r"(?:\bWITH\s+|,\s*)([a-z_][a-z0-9_]*)\s+AS\s*\(",
            sql_blocks,
            re.IGNORECASE,
        )
    )

    referenced -= PROMPT_NON_TABLES
    referenced -= cte_names

    unknown = sorted(t for t in referenced if t not in db_tables)
    for name in unknown:
        report.error(
            "prompt-tables",
            f"the system prompt queries table {name!r}, which does not exist in "
            f"the database. The agent will write SQL that always errors.",
        )

    ok = not unknown
    report.section(f"prompt table references ({len(referenced)} found)", ok)
    return ok


def check_sql_policy(report: Report, metadata: sa.MetaData) -> bool:
    """
    Fail if ``data/sql-policy.toml`` names a table or column the warehouse
    does not have.

    Without this, a typo in a sensitive column's name would not crash
    anything: the guardrails would simply never block the real column.
    """
    from agent_app.nl2sql.guardrails import load_policy, reflect_table_columns

    try:
        load_policy(
            path_toml=path_enum.path_sql_policy_toml,
            schema_name=metadata.schema or "",
            table_columns=reflect_table_columns(metadata),
        )
    except (OSError, ValueError, KeyError) as e:
        report.error("sql-policy", f"{path_enum.path_sql_policy_toml.name}: {e}")
        report.section("sql policy", False)
        return False
    report.section("sql policy", True)
    return True


def check_content_files(report: Report) -> bool:
    """Fail if the hand-written content a swap must replace is missing or empty."""
    ok = True

    for label, path, floor in (
        ("system prompt", path_enum.path_bi_agent_system_prompt_md, 500),
        ("site copy", path_enum.path_site_toml, 500),
        ("business context", path_enum.path_business_context_md, 500),
    ):
        if not path.exists():
            report.error("content", f"{label} missing: {path}")
            ok = False
        elif len(path.read_text(encoding="utf-8").strip()) < floor:
            report.error("content", f"{label} looks like a stub: {path}")
            ok = False

    report.section("content files", ok)
    return ok


def kind_from_phrases(action: str) -> str:
    """Which block this question's wording will actually produce."""
    hits = [
        kind
        for kind, groups in RENDER_PHRASES.items()
        if all(any(p in action for p in group) for group in groups)
    ]
    if len(hits) == 1:
        return hits[0]
    return "ambiguous" if hits else "free"


def check_render_quota(report: Report) -> bool:
    """
    Fail if the kickstart questions do not exercise every renderer.

    Checked in both directions on purpose. ``render`` is what the button
    promises the reader, the phrase is what the model reacts to, and each can be
    wrong without the other noticing: a question marked ``chart`` whose wording
    forgot "as a bar chart" draws a chart icon over a paragraph of prose.
    """
    ok = True
    site_toml = path_enum.path_site_toml
    if not site_toml.exists():
        report.section("render quota", False)
        return False

    actions = tomllib.loads(site_toml.read_text(encoding="utf-8")).get("chat", {}).get(
        "suggestedActions", []
    )
    tally: dict[str, int] = {kind: 0 for kind in RENDER_QUOTAS}

    for i, item in enumerate(actions):
        missing = {"render", "title", "label", "action"} - set(item)
        if missing:
            report.error("quota", f"suggestedActions[{i}] is missing {sorted(missing)}")
            ok = False
            continue

        declared = item["render"]
        if declared not in RENDER_QUOTAS:
            report.error(
                "quota",
                f"suggestedActions[{i}] '{item['title']}': unknown render {declared!r}",
            )
            ok = False
            continue

        tally[declared] += 1
        actual = kind_from_phrases(item["action"].lower())
        if actual != declared:
            report.error(
                "quota",
                f"suggestedActions[{i}] '{item['title']}': render is {declared!r} but "
                f"the wording produces {actual!r}",
            )
            ok = False

    for kind, want in RENDER_QUOTAS.items():
        if tally[kind] != want:
            report.error("quota", f"{tally[kind]} {kind} question(s), expected {want}")
            ok = False

    report.section(f"render quota ({len(actions)} questions)", ok)
    return ok


def run(retired: list[str] | None = None) -> int:
    """Run every check, print one report, and return a shell exit code."""
    print()
    print("Content consistency check")
    print("=" * 60)

    report = Report()
    metadata, no_seed_reason = seed_metadata()

    check_retired_terms(report, retired or [])

    if metadata is not None:
        db_tables = {table.name for table in metadata.tables.values()}
        check_table_insert_order(report, metadata)
        check_prompt_tables(report, db_tables)
        check_sql_policy(report, metadata)
    else:
        # Say the database is missing once, instead of once per consequence.
        # Otherwise the run emits one error per table the prompt mentions, which
        # reads like the prompt is broken when nobody has built the seed yet.
        report.error("seed", no_seed_reason)
        report.section("seed database", False)

    check_content_files(report)
    check_render_quota(report)

    print("=" * 60)

    for warning in report.warnings:
        print(f"WARN   {warning}")
    for error in report.errors:
        print(f"ERROR  {error}")

    if report.errors:
        print()
        print(f"{len(report.errors)} problem(s) found.")
        return 1

    print()
    print("All checks passed.")
    return 0
