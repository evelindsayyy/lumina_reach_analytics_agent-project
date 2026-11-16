# -*- coding: utf-8 -*-

"""
``agent-app ac-gen``: write ``agentcore/`` and ``build/agentcore/`` for the
deployment; ``agent-app ac-gen --teardown``: an empty project, whose deploy
destroys the stack.
"""

from . import codezip
from . import project_files as pf
from . import settings as s
from ..runtimes.common import AGENT_RUNTIME_NAME, MCP_RUNTIME_NAME

#: Each runtime: its module (relative to the package) and whether it speaks HTTP.
RUNTIMES = (
    (MCP_RUNTIME_NAME, "runtimes.analytics_mcp", False),
    (AGENT_RUNTIME_NAME, "runtimes.analytics_agent", True),
)


def generate_all(settings: s.DeploySettings, requirements: list[str]) -> None:
    pf.write_json(s.PATH_AGENTCORE_JSON, pf.build_agentcore_json(settings))
    pf.write_json(s.PATH_AWS_TARGETS_JSON, pf.build_aws_targets_json(settings))
    pf.write_json(s.PATH_APP_CONFIG_JSON, pf.build_app_config(settings))
    for name, module, is_http in RUNTIMES:
        codezip.assemble_runtime_dir(s.DIR_CODEZIP / name, name, module, is_http, requirements)
        print(f"Assembled {(s.DIR_CODEZIP / name).relative_to(s.DIR_AGENTCORE.parent)}")
    print(f"Generated agentcore/ for target {s.TARGET_NAME!r} in {settings.region}")


def generate_teardown(settings: s.DeploySettings) -> None:
    pf.write_json(s.PATH_AGENTCORE_JSON, pf.build_empty_agentcore_json())
    pf.write_json(s.PATH_AWS_TARGETS_JSON, pf.build_aws_targets_json(settings))
    print(f"Generated an empty AgentCore project: deploying it destroys target {s.TARGET_NAME!r}")
