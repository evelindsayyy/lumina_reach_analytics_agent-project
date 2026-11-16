## Context Files

## Code Architecture

### Entry Point

```python
from agent_app.api import one  # Main singleton instance
```

### Directory Structure

```
data/                        # EVERY AUTHORED ARTIFACT a dataset swap rewrites.
│                            #   Content only -- the one config value a swap
│                            #   changes (SCHEMA_NAME) is in .env.defaults.
├── site.toml                #   Every sentence the frontend says, incl. the 12
│                            #   kickstart questions and the 4 capability cards.
├── business-context.md      #   The long-form explainer behind the home page.
├── system-prompt.md         #   The agent's domain brain.
└── sql-policy.toml          #   The dataset's SQL guardrail rules: sensitive
                             #   columns, share columns, conversion sources.

dataset/                     # The dataset's own source material. Committed --
├── 0*-*.md                  #   summary, business context, ER doc, SQL queries
├── 04-*_data_generator*.py  #   ...but its OUTPUT is not: `mise run gen-data`
├── requirements.txt         #   builds <name>.duckdb locally (duckdb only).
└── <name>.duckdb            #   gitignored; discovered by warehouse/engines.py.

agent_app/                   # Python package. Name is deliberately generic and
├── api.py                   #   never changes when the dataset changes.
├── paths.py
├── runtime.py
├── constants.py
├── sql_utils.py
├── ai_sdk_adapter.py
│
├── config.py                # Reads .env + .env.defaults. Nothing else parses
│                            #   configuration; data/ holds content only.
├── cli.py                   # `agent-app` console script (incl. gen-data).
├── content_check.py         # `agent-app check-content`.
├── warehouse/
│   ├── engines.py           #   DuckDB / Snowflake engines; finds the .duckdb file
│   ├── snowflake_ddl.py     #   DuckDB catalog -> Snowflake DDL, grants, cost cap (pure)
│   ├── snowflake_sync.py    #   `agent-app snowflake-sync`: key pair, setup, load, row counts
│   └── dialect.py           #   Snowflake -> DuckDB transpile (sqlglot)
├── nl2sql/
│   └── guardrails.py        #   AST guardrails every agent query passes
├── runtimes/                # The two AgentCore runtimes; same code locally.
│   ├── analytics_agent.py   #   HTTP runtime (8080): AI SDK request in, AI SDK
│   │                        #   v5 stream out; a new agent per turn
│   ├── chat_turn.py         #   One turn: quota, agent, metering, parse. Pure
│   ├── analytics_mcp.py     #   MCP runtime (8000, /mcp): the two data tools
│   ├── mcp_connection.py    #   Local URL, or deployed ARN + SigV4
│   └── common.py            #   Runtime names, ports, the FastMCP settings
├── vendor/                  # Third-party code copied in, not installed.
│   └── vercel_ai_sdk.py     #   AI SDK request-body data model. No project
│                            #   logic goes in here.
│
├── one/
│   ├── one_00_main.py
│   ├── one_01_config.py
│   ├── one_02_db.py
│   ├── one_03_boto3.py
│   ├── one_04_agent.py
│   └── api.py
│
└── db_schema/

app/api/chat/route.ts        # The web tier's only backend: forwards to the agent
                             #   runtime (AGENT_RUNTIME_URL, else 127.0.0.1:8080)

lib/
├── agent-proxy.ts           # The proxy itself, import-free so tests_node runs it
├── icons.ts                 # Icon-name -> component map; exports the IconName type
├── utils.ts                 # cn(): Tailwind class merging
├── seo/                     # <head> metadata, from data/site.toml
└── site/
    ├── schema.ts            # The shape data/site.toml must have, plus the
    │                        #   required-key list checked at load
    └── load.ts              # Parses the TOML once. SERVER ONLY (reads disk).

components/
├── CapabilityCard.tsx       # One business thread. Home page AND agent page
│                            #   render this, from one [[capabilities]] entry.
├── BusinessContextModal.tsx # Renders business-context.md as Markdown
├── ConceptTooltip.tsx       # The hover/focus/tap bubble behind a concept name
└── chat/
    └── RenderBadge.tsx      # The glyph promising what a kickstart draws
```

### The Two Kinds of "Config"

Two files feed `agent_app/config.py`. **The line between them is whether the value
is a secret**, because that is what decides who — and which AI — may open the
file:

| | `.env.defaults` | `.env` |
|---|---|---|
| Holds | `SCHEMA_NAME`, `WAREHOUSE_ENGINE`, LLM provider/model, region, the whole quota block | API keys, AWS keys, the `SNOWFLAKE_*` account and key-pair settings |
| Secret | No | **Yes** |
| In Git | **Yes** | No |
| AI may read | Yes | **No** — `deny` in `.claude/settings.json` |
| AI may edit | Yes — this is what a dataset swap changes | **No** |
| Precedence | Loaded second; fills in the gaps | Loaded **first**; wins |

Rotating an API key must not touch the schema name; pointing the repo at a new
dataset must not touch anyone's credentials.

There is deliberately **no `.env.defaults.example`**. The file is committed, so
it *is* the reference. A gitignored-plus-template arrangement would put
`SCHEMA_NAME` outside version control, make every clone re-enter it, and hide an
AI's swap edits from review — which is the opposite of the point.

`data/` is the third leg and holds no config at all: only authored content
(copy, prompt, explainer, SQL policy).

**The test for which file a value belongs in: is it a secret?** Not "does it
vary by environment" — that used to be the question, when the split was
`data/dataset.toml` vs `.env`, and it produced a whole TOML file plus a reader
module for what ended up being one string. The split that earns its keep is the
one that decides *who may touch the file*:

- `.env` holds credentials. It is gitignored, and `.claude/settings.json` denies
  an AI both `Read` and `Edit` on it.
- `.env.defaults` holds everything that is not a credential, including the
  dataset's `SCHEMA_NAME`. It is committed, so a change shows up in `git diff`
  like any other, and an AI doing a dataset swap may edit it freely.

`.env` is loaded first and wins, so any committed default can be overridden on
one machine by repeating the key in `.env` — that is how a checkout points at a
staging schema without editing a committed file.

A value still must not have two homes *within* a layer. `project_name` was once
duplicated between `Config` and the dataset config and is gone entirely;
`schemaName` and `project.name` were two names for one thing and are now one.

**`data/` is content, not config.** Everything in it is authored prose, copy, or
data: the frontend's strings, the explainer, the system prompt, the SQL policy.
Nothing in `agent_app/` parses a config file out of it. Before adding something
there, ask whether a human wrote it as content; if it is a setting, it goes in
`.env.defaults`.

**Why the site copy is TOML rather than TypeScript.** It used to be
`config/site.ts`, and the argument for that was real: the compiler checked the
shape for free and a misspelled icon name was a build error. What outweighed it
is that the copy belongs to the *dataset*, not to the frontend. Keeping it in
`lib/`-adjacent TypeScript meant a dataset swap was a diff scattered across the
repo; keeping every authored artifact in `data/` makes a swap a directory
replacement, which is a far easier thing to get right and to review.

The checks the compiler used to perform are not gone, they moved into
`lib/site/load.ts` and run when Next.js reads the file: `REQUIRED_SITE_KEYS`
rejects a missing key by name, and `assertIconsExist` rejects an icon that is
not in `lib/icons.ts`. Both throw during `next build`, so a broken `site.toml`
still cannot ship. What genuinely got weaker is editor autocomplete while
authoring the TOML. That was judged an acceptable trade, because authoring
happens once per dataset while reviewing a swap happens every time.

**Both directions of the kickstart contract are machine-checked.** Each of the
12 questions in `site.toml` carries a `render` field, and its `action` carries
the literal trigger phrase that makes the block appear. `mise run cli-check-content` fails
if the two disagree, in either direction: a wrong phrase means the block never
appears, and a wrong `render` means the button draws an icon promising a chart
over an answer that is prose.

**Comments and identifiers are English only.** Every comment, docstring, and
name in the source tree (`.ts`, `.tsx`, `.py`) is written in English, even when
the conversation that produced it was in Chinese. Chinese belongs in
`.claude/skills/*-cn/` docs and in chat, never in code. Mixed-language comments
make the codebase unreadable for anyone who joins later and unsearchable by
keyword.

**No author identity anywhere.** This site presents a product, not a person.
There is no name, photo, contact link, or `author`/`creator` page metadata, and
none should be added — that was portfolio scaffolding the app inherited and does
not need.

### Swapping the Dataset

Everything that varies between datasets lives in `data/`. When adding UI copy, a
brand string, or a business term, put it in `data/site.toml` — never inline it
in a component.

| What | Where |
|---|---|
| Product name, all UI copy, SEO, icons | `data/site.toml` |
| The 4 capability cards (home page *and* agent page) | `[[capabilities]]` in `data/site.toml` |
| The 12 kickstart questions, with their render quota | `[[chat.suggestedActions]]` in `data/site.toml` |
| The long-form "what problem does this solve" explainer | `data/business-context.md` |
| The warehouse schema name | `SCHEMA_NAME` in `.env.defaults` |
| Agent's domain knowledge | `data/system-prompt.md` |
| SQL guardrail rules (sensitive / share columns, conversion sources) | `data/sql-policy.toml` |
| The data itself | `dataset/` — source docs plus the generator that builds `<name>.duckdb` |
| Dataset-specific write tools | `@mcp.tool()` functions in `runtimes/analytics_mcp.py` |

The only entry not in `data/` is the last one, because a write tool is code.

Run `mise run gen-data`, then `mise run cli-check-content`. The check reads the
DuckDB file (always, whatever `WAREHOUSE_ENGINE` says) and fails on a warehouse
whose foreign keys form a cycle (or that has no tables at all), a prompt that
queries a nonexistent table, a `sql-policy.toml` that names a table or column
the warehouse lacks, missing content files, and a kickstart question whose
`render` disagrees with its own wording. Right after a swap also run it with the outgoing domain's
vocabulary, which is a one-off argument rather than committed state:

```bash
mise run cli-check-content -- --retired "patient,bed,ward,nurse"
```

Icon names are checked by `mise run build-web`, not by `mise run cli-check-content`:
`lib/site/load.ts` rejects any `icon` that `lib/icons.ts` does not export. Run
the build too, since the check script never parses the TOML's icon fields.

### When to Modify Each File

**Root Level Modules:**

| File | What It Does | When to Modify |
|------|--------------|----------------|
| `api.py` | Re-exports `one` singleton | Rarely. Only if you need to expose additional top-level imports. |
| `paths.py` | Defines all file/directory paths as `PathEnum`, including the system prompt | When adding new files (prompts, data files, output paths). Add path here first, then use `path_enum.your_new_path` everywhere. Paths are source-tree facts, so they are never named in config. Never add one speculatively: an entry with no reader rots into a pointer at a directory that no longer exists. |
| `runtime.py` | Detects runtime environment (local vs vercel). Only the Python processes read it, and since M2b none runs on Vercel | When adding a new deployment target (e.g., AWS Lambda). Add new enum value and detection logic. |
| `constants.py` | Shared enums: the LLM provider list, and the schema-encoding vocabulary | When adding an enum a *second* module needs. A constant with one reader belongs next to that reader, not here. |
| `utils.py` | Helpers with no project dependencies: `debug` (stderr, never stdout) and `match` (include/exclude patterns) | Same rule as `constants.py` — only what a *second* module needs. |
| `sql_utils.py` | Pure functions for SQL execution and formatting. Owns one promise: a query run through `execute_sql_query` cannot change the database | When changing how SQL results are formatted. Every failure is *returned as text*, never raised — the caller is an LLM, and a traceback ends its turn. |
| `warehouse/engines.py` | `find_duckdb_file`, `new_duckdb_engine` (read-only, `search_path` = `SCHEMA_NAME`), `new_snowflake_engine` (key-pair service user) | When changing how either warehouse is connected to. |
| `agentcore_project/` | `agent-app ac-gen`: `settings.py` (fixed names, `DeploySettings` from `.env.defaults` + `.env` + the STS account), `project_files.py` (`agentcore.json` with each runtime's own `envVars`, `aws-targets.json`, `app-config.json` for the stack), `codezip.py` (`build/agentcore/<Runtime>/`: shim, pinned deps, `agent_app/` minus this package, `data/`, `.env.defaults`) | When a runtime's environment, packaging or the deployment's names change. Dev-machine only: never shipped. |
| `agentcore/cdk/lib/cdk-stack.ts` | The one stack: both runtimes, `bind()`, Cognito + the agent's JWT authorizer, the MCP role's SSM grant and Bedrock Deny, the agent's SSM Deny, the quota table | When IAM, auth or AWS resources change. Check the synthesized template after any edit (`mise run ac-build`). |
| `warehouse/snowflake_ddl.py`, `warehouse/snowflake_sync.py` | The Snowflake copy of the DuckDB file: `read_catalog`, `render_*` (schema, account setup with the cost cap, read grants, load), and `run` (`mise run wh-snowflake-sync`, signed in as `SNOWFLAKE_ADMIN_USER` with the key pair of `wh-snowflake-admin-key`; both key pairs live in git-ignored `tmp/snowflake/`) | When the deployed warehouse's objects, grants or cost cap change. A new DuckDB column type needs a `TYPE_MAP` entry; a Snowflake reserved name is refused on purpose. |
| `warehouse/dialect.py` | `transpile_to_duckdb`: Snowflake SQL -> DuckDB, with sqlglot | When a Snowflake construct does not transpile. SQL is written in the Snowflake dialect everywhere — prompt, guardrails, `dataset/03-*` queries. |
| `nl2sql/guardrails.py` | AST guardrails (sqlglot, Snowflake dialect): `PARSE_ERROR`, `MULTI_STATEMENT`, `NOT_SELECT`, `UNKNOWN_TABLE`, `SENSITIVE_COLUMN`, `UNKNOWN_COLUMN`, `CONVERSION_MIX`, `RATIO_AVG`; rewrites `CURRENT_DATE` to the data's reference date and adds a `LIMIT` | When adding a generic check. The table/column allowlist comes from reflection and the dataset rules from `data/sql-policy.toml`, so a dataset swap edits neither this module nor its tests. |
| `ai_sdk_adapter.py` | Converts Vercel AI SDK messages <-> Strands Agent messages, and generates the SSE event stream back to the browser | When the frontend message format changes. **Not** when switching LLM provider — this file is provider-agnostic and must stay that way; provider code belongs in `one_04_agent.py`. |
| `vendor/vercel_ai_sdk.py` | Pydantic data model for the AI SDK request body. Vendored from `vercel-ai-sdk-mate`, deliberately lenient so a new AI SDK release cannot break request parsing | When the frontend starts sending a message part type the backend needs to read: add the model class and one line to `PART_MODEL_BY_TYPE`. Keep it a pure data model — no provider logic. |

**config/ Directory:**

| File | What It Does | When to Modify |
|------|--------------|----------------|
| `config.py` | The `Config` dataclass, and `load_env_files()` which reads `.env` then `.env.defaults` | When adding an environment variable: add a field, load it in **both** `new_in_local_runtime()` and `new_in_vercel_runtime()`, and document it in `.env.defaults` (not a secret) or `.env.example` (secret). There is no module-level `config` singleton — callers use `one.config`. |

**one/ Directory (Main Class + Mixins):**

| File | What It Does | When to Modify |
|------|--------------|----------------|
| `one_00_main.py` | Defines `One` class that inherits all mixins; creates `one` singleton | When adding a new mixin (import it and add to inheritance list). |
| `one_01_config.py` | `ConfigMixin`: provides `self.config` | Rarely. Config loading logic is in `config.py`. |
| `one_02_db.py` | `DbMixin`: provides `self.engine` (chosen by `WAREHOUSE_ENGINE`), `self.db_type`, `self.reflected_metadata` (tables and views), `self.database_schema_str`, `self.guardrail_policy`, `self.execute_sql_query` | When changing engine selection or the guardrails -> transpile -> execute pipeline. |
| `one_03_boto3.py` | `Boto3Mixin`: provides `self.boto_ses`, `self.bedrock_runtime_client()` | When adding new AWS service clients (S3, DynamoDB, etc.). |
| `one_04_agent.py` | `AgentMixin`: provides `self.model` (the strands model of `LLM_PROVIDER`) and the agent's own `tool_write_debug_report` | When adding an LLM provider. Data tools are not here: they are on the MCP server, `runtimes/analytics_mcp.py` |
| `api.py` | Exports `one = One()` singleton | Rarely. Only touched when restructuring exports. |

**data/ Directory (everything a dataset swap rewrites):**

| File | What It Does | When to Modify |
|------|--------------|----------------|
| `system-prompt.md` | System prompt for the BI agent | When changing agent behavior, adding tool usage instructions, or updating workflow guidelines. The five rendering sections are copied verbatim from `.claude/skills/swap-dataset-cn/ref/system-prompt-render-blocks.md`; change them in both places or neither. |
| `site.toml` | Every sentence the UI says, the 4 capability cards, the 12 kickstart questions | When changing any user-visible string. Never inline copy in a component. |
| `business-context.md` | The long-form explainer behind the home page | When the domain explanation changes. At most one mermaid diagram in the file. |
| `sql-policy.toml` | Dataset rules for the SQL guardrails: sensitive columns, share columns (no `AVG`), conversion sources that must not be mixed | When the dataset's sensitive or ratio columns change. `cli-check-content` fails if it names a table or column the warehouse lacks. |

**db_schema/ Directory:**

Three steps in one direction — reflect, model, encode — and nothing flows back.

| File | What It Does | When to Modify |
|------|--------------|----------------|
| `extractor.py` | SQLAlchemy metadata -> the models. Owns `SQLALCHEMY_TYPE_MAPPING`, the compression from SQL types to the LLM vocabulary | When a reflected type comes out as a raw dialect spelling instead of a compact one. |
| `model.py` | The intermediate representation | **Only together with the encoder line that emits the new field.** Every field here has a reader; extracting one nobody encodes reads as a promise the output does not keep. |
| `encoder.py` | The models -> the compact string the agent is shown. Pure formatting, no database access | When changing how the schema is presented to the LLM. Re-run `mise run cli-print-db-schema` and eyeball the diff — this string is the agent's entire picture of the database. |
| `api.py` | Public re-exports | When adding a function the rest of the app calls. |

Scoped to what this app runs on. `DbTypeEnum` lists only engines with code
paths — `DUCKDB` and `SNOWFLAKE` (the two `WarehouseEngineEnum` values), plus
`SQLITE` for the in-memory databases of the unit tests — rather than the ten it
once advertised: a menu of unimplemented options reads as support that does not
exist. The type
mapping is the deliberate exception: a missing key degrades to the dialect's own
spelling rather than failing, so breadth there costs nothing.

### Class Hierarchy

```
One (one_00_main.py)
├── ConfigMixin (one_01_config.py)
│   └── self.config -> Config instance (from config.py)
│
├── DbMixin (one_02_db.py)
│   ├── self.engine                -> DuckDB file or Snowflake, by WAREHOUSE_ENGINE
│   ├── self.db_type               -> DbTypeEnum of that engine
│   ├── self.reflected_metadata    -> Tables AND views of SCHEMA_NAME
│   ├── self.database_schema_str   -> LLM-optimized schema string
│   ├── self.guardrail_policy      -> Reflected allowlist + data/sql-policy.toml
│   └── self.execute_sql_query(sql)        -> Guardrails -> transpile (DuckDB) -> Markdown table
│
├── Boto3Mixin (one_03_boto3.py)
│   ├── self.boto_ses              -> boto3.Session
│   └── self.bedrock_runtime_client() -> BedrockRuntimeClient
│
└── AgentMixin (one_04_agent.py)
    ├── self.bedrock_model         -> BedrockModel (strands)
    ├── self.model                 -> the strands model of LLM_PROVIDER
    └── tool_write_debug_report    -> the agent's own tool (returns, never raises)
```

There is no `one.agent`. The agent is built per request in
`runtimes/analytics_agent.py` (`build_agent`): `one.model`, the system prompt,
the history the client sent, and two tool sources -- an `MCPClient` of the
`AnalyticsMcp` runtime and `one.tool_write_debug_report`.

### The Two Runtimes

```
Browser -> Next.js /api/chat (proxy) -> AnalyticsAgent :8080 -> MCP -> AnalyticsMcp :8000 -> warehouse
```

| | `AnalyticsAgent` | `AnalyticsMcp` |
|---|---|---|
| Module | `runtimes/analytics_agent.py` | `runtimes/analytics_mcp.py` |
| AgentCore contract | HTTP: `POST /invocations`, `GET /ping`, port 8080 | MCP: stateless streamable HTTP, `/mcp`, port 8000 |
| Server | `BedrockAgentCoreApp` | `FastMCP` |
| Reads | `LLM_PROVIDER` and its key | the warehouse (DuckDB file or Snowflake key) |
| Never | opens a warehouse connection | calls a model |

- **Request and response are the AI SDK's.** The agent runtime takes the
  request body the UI posts and returns the v5 UI message stream (a Starlette
  `StreamingResponse`, which `BedrockAgentCoreApp` passes through), so the web
  tier forwards both without parsing.
- **A new agent per turn** (`chat_turn.run_chat_turn`). The UI resends the
  conversation each time, so nothing is cached between requests, and two chats
  cannot see each other's messages. Metering reads the fresh agent's
  `accumulated_usage`, which is therefore exactly the turn's.
- **Every failure is an answer, not a 500**: no message, spent quota, MCP
  unreachable, model throttled or failed. Each is a sentence in
  `agent_response.py` / `chat_turn.py`; the details go to the log.
- **Retries are capped** (`MODEL_RETRY_STRATEGY`: three attempts, about six
  seconds). The strands default spent two minutes retrying a daily token cap.
- **Finding the MCP server**: `MCP_URL_ANALYTICSMCP` (set by `mise run dev`),
  else `AGENTCORE_RUNTIME_ANALYTICSMCP_ARN`, which the AgentCore CLI's
  `bind()` sets on a deployed agent; then every request is SigV4-signed with
  the agent's execution role.

### Pure Functions vs Bound Methods

| Type | Location | Characteristics |
|------|----------|-----------------|
| **Pure Functions** | `sql_utils.py` | Take `engine` as first param, no class dependency |
| **Bound Methods** | `one/one_*.py` | Use `self.config`, `self.engine`, etc. |

**Write operations:** none ship by default. They are inherently dataset
specific, so a dataset that needs them adds `@mcp.tool()` functions in
`runtimes/analytics_mcp.py`, where the warehouse connection is. Keep the underlying helpers
pure — `engine` as the first parameter, returning a dict — the way `sql_utils.py`
does.

**Pure Functions (sql_utils.py):**
- `format_result(result)` - Format SQL result as Markdown table
- `ensure_valid_select_query(query)` - Validate SELECT statement
- `execute_sql_query(engine, sql)` - Execute a query in an always-rolled-back transaction, return Markdown
- `new_sqlite_engine(path)` - Open SQLite so that the rollback guarantee holds (used by the unit tests)

`DbMixin.execute_sql_query` wraps the last one: it runs `validate_sql` first
(a rejection comes back as `Error: rejected by the SQL guardrails. ...`),
transpiles to DuckDB when that is the engine, and appends a note naming the
conversion source used or any reference-date rewrite.

### Key Singletons

```python
from agent_app.api import one           # Main app instance
from agent_app.paths import path_enum   # All paths
from agent_app.runtime import runtime   # Runtime detection

one.config.schema_name                 # SCHEMA_NAME, from .env.defaults
one.config.warehouse_engine            # WAREHOUSE_ENGINE: "duckdb" | "snowflake"
```

### Agent Framework

- **Library**: `strands` (Strands Agents SDK)
- **Model**: AWS Bedrock (configurable via `config.model_id`)
- **Tools**: the data tools are `@mcp.tool()` functions in `runtimes/analytics_mcp.py`; the agent's own tool is `tool_write_debug_report` in `one_04_agent.py`
- **System Prompt**: `data/system-prompt.md`

---

## Development Setup

**Package Managers:**
- Python: uv (via mise)
- Node.js: pnpm (via mise)

**Core Configuration Files:**
- `data/site.toml` - All frontend copy and identity (swapped per dataset)
- `.env.defaults` - Committed, non-secret config incl. `SCHEMA_NAME`. AI-editable
- `.env` - Secrets. Gitignored, and denied to AI in `.claude/settings.json`
- `mise.toml` - Project tasks and tool versions (Python 3.12, Node 24, uv, pnpm)
- `pyproject.toml` - Python dependencies and project metadata
- `package.json` - Node.js dependencies
- `.venv/` - Python virtual environment directory
- `node_modules/` - Node.js dependencies directory

**Environment Variables (.env):**

> ⚠️ **Never read, print, or otherwise open `.env`.** It holds real credentials —
> API keys, the Snowflake private key, AWS tokens. Read `.env.example` instead: it is the
> committed, placeholder-only template and documents every supported variable.
> If you need to know whether a variable is *set*, check for the key name via
> `.env.example`, or ask the user — do not `cat` / `Read` the `.env` file.

See `.env.example` for the fully documented template. The key switch is `LLM_PROVIDER`:
exactly one LLM backend is active per process, and only *that* provider's credential
is required.

```bash
# bedrock (default) | anthropic | openai | google
LLM_PROVIDER=bedrock
AWS_REGION=us-east-1

# Optional: override the provider's default model (formats are NOT interchangeable)
# LLM_MODEL_ID=us.amazon.nova-lite-v1:0

# Only the key matching LLM_PROVIDER is needed
# ANTHROPIC_API_KEY=sk-ant-...   (requires: uv sync --extra anthropic)
# OPENAI_API_KEY=sk-...          (requires: uv sync --extra openai)
# GOOGLE_API_KEY=...             (requires: uv sync --extra gemini)

# Only when WAREHOUSE_ENGINE="snowflake" (.env.defaults; default "duckdb" needs none).
# A key-pair service user: no password exists, its role holds only USAGE + SELECT.
# SNOWFLAKE_ACCOUNT=myorg-myaccount
# SNOWFLAKE_USER=...
# SNOWFLAKE_ROLE=...
# SNOWFLAKE_WAREHOUSE=...
# SNOWFLAKE_DATABASE=...
# SNOWFLAKE_PRIVATE_KEY_PATH=tmp/snowflake/...pem   (or SNOWFLAKE_PRIVATE_KEY=<PEM>, which wins)
```

The default `WAREHOUSE_ENGINE="duckdb"` opens the local file read-only; set
`DUCKDB_PATH` only to point at a file other than the discovered
`dataset/*.duckdb`.

For `LLM_PROVIDER=bedrock` locally, do **not** set `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` in `.env` — boto3 reads env vars before `~/.aws/credentials`,
so a placeholder there shadows a working local profile.

---

## Tests

**Python Tests:**
- Location: `tests_python/`
- Runner: pytest
- Command: `mise run test-python`

**Test File Mapping:**
```
tests_python/
├── test_config.py                  # Tests for config.py
├── db_schema/
│   ├── test_db_schema_encoder.py   # Tests for encoder.py
│   └── test_db_schema_extractor.py # Tests for extractor.py
├── nl2sql/
│   └── test_nl2sql_guardrails.py   # Tests for guardrails.py (fictional acme policy)
├── warehouse/
│   └── test_warehouse_engines.py   # Tests for engines.py and dialect.py
├── runtimes/
│   ├── test_runtimes_analytics_mcp.py   # Data tools, direct and over an in-memory MCP session
│   ├── test_runtimes_analytics_agent.py # HTTP contract via Starlette's TestClient, agent stubbed
│   ├── test_runtimes_chat_turn.py       # One turn with a stub agent: answers, refusals, failures
│   └── test_runtimes_mcp_connection.py  # Local URL vs ARN + SigV4
├── one/
│   ├── test_one_one_00_main.py     # Tests for One class
│   ├── test_one_one_01_config.py   # Tests for ConfigMixin
│   └── test_one_one_02_db.py       # Tests for DbMixin (needs the DuckDB file)
├── test_api.py                     # Tests for api.py
├── test_cli.py                     # Tests for cli.py
├── test_content_check.py           # Tests for content_check.py
├── test_sql_utils.py               # Tests for sql_utils.py (in-memory SQLite)
├── test_source_code.py             # Tests for source_code.py (the TDD lesson)
└── test_utils.py                   # Tests for utilities
```

**Build the warehouse before testing.** Tests that go through `one.engine` (e.g.
`test_one_one_02_db.py`) read the real `dataset/*.duckdb`, so a fresh checkout
runs `mise run gen-data` first.

**No test opens a network connection.** The `db_schema` and `sql_utils` tests
reflect or query in-memory SQLite, which is enough because that code only ever
touches SQLAlchemy objects. The Snowflake engine is built in
`test_warehouse_engines.py` but never connected; `mise run cli-test-db-conn` is
the only thing that reaches a real Snowflake account.

**Use a fictional domain in test fixtures** (`acme`, `widget`, `part`), never
this dataset's real table names. A test asserting on `campaign` silently becomes
a lie the next time the dataset is swapped.

**Node.js Tests:**
- Location: `tests_node/` (`*.test.mjs`; Node 24 strips the types of `lib/agent-proxy.ts` itself)
- Runner: Node's built-in test module
- Command: `mise run test-node`

---

## Available Tasks

- `mise run venv-create` - Create Python virtual environment
- `mise run venv-remove` - Remove virtual environment
- `mise run inst-python-deps` - Install Python dependencies
- `mise run inst-node-deps` - Install Node.js dependencies
- `mise run inst` - Install all dependencies (Python + Node.js)
- `mise run test-python` - Run Python tests
- `mise run test-node` - Run Node.js tests
- `mise run test` - Run all tests (content consistency + Python + Node.js)
- `mise run cov` - Run tests with a coverage report, written to `htmlcov/`
- `mise run export` - Export Python requirements to requirements.txt
- `mise run dev` - Start all development servers (Next.js on 3000, agent runtime on 8080, MCP runtime on 8000; auto-kills this project's old instances first)
- `mise run agent-dev` / `mise run mcp-dev` - Start one runtime alone
- `mise run kill` - Kill this project's development servers
- `mise run build-web` - Build the Next.js frontend; the only check for `site.toml` keys and icon names
- `mise run gen-data` - Build `dataset/<name>.duckdb` from the dataset's generator (= `agent-app gen-data`; replaces any existing `.duckdb` file)

Tasks prefixed `cli-` are one-line wrappers over the `agent-app` console script, grouped
under a `# cli` banner in `mise.toml`. A task without the prefix does its own work; one
with it is a door onto a subcommand you can also run directly:

- `mise run cli-check-content` - Verify `data/` still agrees with the prompt and the DuckDB file (run after a dataset swap)
- `mise run cli-test-db-conn` - Check the configured warehouse (`WAREHOUSE_ENGINE`) answers `SELECT 1` on `one.engine`
- `mise run cli-print-db-schema` - Print the schema exactly as the agent is shown it

`check-content` and `build-web` are the two halves of "did the swap land", and
neither catches what the other does. Run both.

### The app's own CLI

```bash
.venv/bin/agent-app gen-data [--seed 42]
.venv/bin/agent-app check-content
.venv/bin/agent-app check-content --retired "patient,bed,ward"
.venv/bin/agent-app test-db-conn
.venv/bin/agent-app print-db-schema
```

Installed as a console script by `[project.scripts]` in `pyproject.toml`, backed
by `agent_app/cli.py`. **`mise.toml` calls this name rather than a file path**, so
where a command's implementation lives can change without every task and habit
changing with it.

**The interface is derived, not declared.** `agent_app/cli.py` hands a `Cli` class
to `fire`: one public method is one subcommand, and that method's signature is the
subcommand's options. Adding a command is adding a method — there is no parser to
keep in step with it, which is what the previous hand-written `argparse` tree cost.
`fire` accepts either spelling of a method name, so `test-db-conn` and `test_db_conn`
both work; the hyphenated one is what the docs and tasks use.

**Every command raises `SystemExit` rather than returning a code.** `fire` prints a
returned value and then exits 0, so a check that returned 1 would print `1` and pass.

`test-db-conn` names no schema and no table on purpose. When the agent is not working
it separates *cannot reach the database* from *reached it, but the schema is empty* —
two failures that otherwise look alike.

**Only application commands belong here** — building the local warehouse file
included: in this repo the dataset is part of the app. `gen-data` discovers the
single `dataset/04-*generator*.py` rather than naming it, so a dataset swap never
edits `agent_app/`.

### Running the dev server from an agent session

`mise run dev` never exits on its own. Three rules follow from that, and the
cost of breaking them is a session that looks hung for half an hour.

**1. Never wait on it in the foreground.** Start it with `run_in_background`, or
detached with `nohup`. A foreground call blocks until the server dies, which is
whenever the user happens to stop it.

**2. Wait for readiness in a separate background command that exits by itself.**
One notification, arriving in seconds:

```bash
until grep -q "Ready in" <task-output-file>; do sleep 0.5; done
```

All three have to be up, and they log different lines: Next.js prints
`Ready in`, the agent prints `serving on port 8080`, the MCP runtime prints
`Uvicorn running on http://127.0.0.1:8000`. Next.js runs as
`next dev --webpack` (Turbopack's dev server cannot resolve the multi-parameter
`next/font/google` URL in `app/layout.tsx`; see the comment in `mise.toml`), and
`next.config.js` pins `turbopack.root` to this repo so a stray lockfile further
up never becomes the workspace root. Do not poll with a
bare `for` loop and no `sleep` -- that spins the CPU and returns instantly
whether or not the thing ever became ready.

**3. Decide who owns the server before you start it.**

| Why you are starting it | How | Cleanup |
| :--- | :--- | :--- |
| To verify something yourself | `run_in_background` | `TaskStop` as soon as you are done |
| The user asked for a server to use | `nohup ... &`, detached | Leave it; tell the user how to stop it |

A backgrounded task that is still holding a server when the user replaces it
emits a stale failure notification much later -- `mise run dev` exits 143 when
its `kill` dependency terminates the previous instance, which reads as
`task failed` even though nothing went wrong. Detaching a server the user owns
avoids that entirely.

**Interpreting an exit code from `mise run dev`:**

| Code | What happened |
| :--- | :--- |
| 143 | SIGTERM. Normally a second `mise run dev` in this same checkout replaced it. Not an error |
| 1 from the `kill` step, no server started | A dev port is held by a process from another checkout. Intended: stop that one, or `--force`. See `kill-dev-servers.py` |

---

## Database

**One schema, two engines,** chosen by `WAREHOUSE_ENGINE` in `.env.defaults`:

| | `duckdb` (default) | `snowflake` |
|---|---|---|
| Where | local file `dataset/<name>.duckdb`, opened read-only | the deployed warehouse, via `snowflake-sqlalchemy` |
| Auth | none | key-pair service user (`SNOWFLAKE_*` in `.env`, see `.env.example`); role has only `USAGE` + `SELECT` |
| Schema / tables | `lumina_reach`: 21 tables + 2 views (`v_reference_date`, `mv_attribution_six_models`) | the same schema, same names — **identical** |
| Used by | development, tests, evaluation | deployment |

**SQL is written in the Snowflake dialect everywhere** — the system prompt, the
guardrails, the golden queries in `dataset/03-*`. On DuckDB,
`agent_app/warehouse/dialect.py` transpiles the validated query with sqlglot
just before it runs, so every SQL example is written once and is right on both
engines.

**The database is not in Git.** `dataset/` holds the source documents and the
generator; `dataset/.gitignore` excludes the `.duckdb` file it produces. A fresh
checkout therefore has to build it (`dataset/requirements.txt` is just `duckdb`,
already a project dependency):

```bash
mise run gen-data          # = .venv/bin/agent-app gen-data [--seed 42]
```

`agent_app/warehouse/engines.py:find_duckdb_file` **discovers** that file rather
than naming it — the filename belongs to the dataset, and naming it would make a
swap edit `agent_app/`, which is the one thing that package is not supposed to
need. Zero matches and several matches both raise, with the fix in the message.
A file named exactly like its schema is rejected too: DuckDB names the catalog
after the file, which would make every qualified reference ambiguous.

The isolation is a **schema**, not a table-name prefix: `SCHEMA_NAME` in
`.env.defaults`, set as the DuckDB `search_path` and as the Snowflake URL's
schema, so the agent writes `FROM campaign` and never names the schema. Table
names are the same on both engines, and that is the whole point — a prefix that
depended on which engine was behind it would make every SQL example in the
system prompt right in one environment and wrong in the other, with nothing
failing loudly. `reflected_metadata` reflects only that schema (tables **and**
views), so the agent never sees anything else, and the guardrails' `UNKNOWN_TABLE`
refuses anything outside it.

**Every agent query passes three layers**, with guardrail and execution failures
returned as text:
`nl2sql/guardrails.py` (AST checks, rules from reflection plus
`data/sql-policy.toml`), the DuckDB transpile, then `sql_utils.execute_sql_query`
in a transaction that is always rolled back, on a read-only connection.

Dependency order is **computed, not configured**: SQLAlchemy's
`metadata.sorted_tables` is a topological sort of the reflected foreign keys.
**Adding a table needs no config change.** `mise run cli-check-content` verifies
the one thing derivation *cannot* fix — that the foreign keys admit an order at
all, i.e. contain no cycle.

**Schema Reference:**
- Run `mise run cli-print-db-schema` to print the schema.
  There is deliberately no checked-in copy: a snapshot of a generated artifact can
  only ever be right by coincidence, and this one had no reader.

**Print LLM-Optimized Schema:**
```bash
mise run cli-print-db-schema
```

**Run SQL Locally:** open `dataset/<name>.duckdb` in DBeaver or the `duckdb` CLI
(`duckdb -readonly dataset/<name>.duckdb`, then `SET search_path = 'lumina_reach'`).
Note that a client speaks DuckDB SQL, not the Snowflake dialect the agent writes.
The repo ships no script for it — a client does it better.

---

## Scripts

`scripts/` is nearly gone. It used to hold a numbered setup sequence; every step of
it now lives where it belongs, which is the point:

| What it used to be | Where it went |
|---|---|
| `test_00` config preflight | `mise run cli-check-content` |
| `test_02` / `test_03` run SQL locally | Nothing. Open the `.duckdb` file in DBeaver or the `duckdb` CLI |
| `test_04` print the LLM schema | `mise run cli-print-db-schema` |
| `test_05` database connectivity | `mise run cli-test-db-conn` |
| `test_06` / `test_07` build and verify the data | `mise run gen-data`, then `mise run cli-check-content` |
| `test_11`–`test_15` per-provider probes | Not in this repo |

Only `test_agent.py` is left.

**Do not add anything to `scripts/`.** A new command is part of the application,
so it goes in `agent_app/cli.py`, plus a one-line `cli-` task in `mise.toml`
(the dataset build is one too: `agent-app gen-data`, run as `mise run gen-data`).
