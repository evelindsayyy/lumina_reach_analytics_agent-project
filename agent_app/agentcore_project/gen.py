# -*- coding: utf-8 -*-

"""
``agent-app ac-gen``: write ``agentcore/`` and ``build/agentcore/`` for the
deployment; ``agent-app ac-gen --teardown``: an empty project, whose deploy
destroys the stack.
"""

import dataclasses

from . import codezip
from . import project_files as pf
from . import settings as s
from ..config import Config
from ..db_schema.snapshot import SchemaSnapshot
from ..db_schema.snapshot import write_snapshot
from ..paths import path_enum
from ..runtimes.common import AGENT_RUNTIME_NAME, MCP_RUNTIME_NAME

#: Each runtime: its module (relative to the package) and whether it speaks HTTP.
RUNTIMES = (
    (MCP_RUNTIME_NAME, "runtimes.analytics_mcp", False),
    (AGENT_RUNTIME_NAME, "runtimes.analytics_agent", True),
)


def schema_snapshot(config: Config, warehouse_engine: str) -> SchemaSnapshot:
    """
    Reflect ``config``'s schema on ``warehouse_engine`` (connecting to it),
    as the MCP runtime would at start-up without a snapshot.
    """
    from ..one.one_00_main import One

    other = One()
    other.__dict__["config"] = dataclasses.replace(config, warehouse_engine=warehouse_engine)
    return other.new_schema_snapshot()


def generate_all(settings: s.DeploySettings, requirements: list[str], snapshot: SchemaSnapshot) -> None:
    """
    :param snapshot: the deployed schema, shipped with the MCP runtime only
        (the agent holds no warehouse setting) so its cold start skips reflection.
    """
    pf.write_json(s.PATH_AGENTCORE_JSON, pf.build_agentcore_json(settings))
    pf.write_json(s.PATH_AWS_TARGETS_JSON, pf.build_aws_targets_json(settings))
    pf.write_json(s.PATH_APP_CONFIG_JSON, pf.build_app_config(settings))
    for name, module, is_http in RUNTIMES:
        codezip.assemble_runtime_dir(s.DIR_CODEZIP / name, name, module, is_http, requirements)
        print(f"Assembled {(s.DIR_CODEZIP / name).relative_to(s.DIR_AGENTCORE.parent)}")
    write_snapshot(s.DIR_CODEZIP / MCP_RUNTIME_NAME / path_enum.path_schema_snapshot_json.name, snapshot)
    print(f"Generated agentcore/ for target {s.TARGET_NAME!r} in {settings.region}")


def generate_teardown(settings: s.DeploySettings) -> None:
    pf.write_json(s.PATH_AGENTCORE_JSON, pf.build_empty_agentcore_json())
    pf.write_json(s.PATH_AWS_TARGETS_JSON, pf.build_aws_targets_json(settings))
    print(f"Generated an empty AgentCore project: deploying it destroys target {s.TARGET_NAME!r}")
