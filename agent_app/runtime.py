# -*- coding: utf-8 -*-

"""
Where am I running?

One question, one place, so that no other module reads the environment to find
out. Detection lives here, the consequences live in ``config.py``: adding a
deployment target means an ``is_*`` method here and a factory there, and nothing
else in the codebase learns a new target exists.
"""

import os

from functools import cached_property

#: Set to :data:`IS_AGENTCORE_RUNTIME_VALUE` in every runtime's ``envVars``
#: (``agentcore.json``, written by ``agent-app ac-gen``). Our own signal, not
#: one AgentCore sets, so detection never depends on an undocumented variable.
IS_AGENTCORE_RUNTIME_VAR = "IS_AGENTCORE_RUNTIME"
IS_AGENTCORE_RUNTIME_VALUE = "true"


class Runtime:
    """Singleton-style runtime detector. Use the ``runtime`` instance, not this class."""

    @cached_property
    def _is_vercel(self) -> bool:
        # See https://vercel.com/docs/environment-variables/system-environment-variables
        return os.environ.get("VERCEL") == "1"

    @cached_property
    def _is_agentcore(self) -> bool:
        return os.environ.get(IS_AGENTCORE_RUNTIME_VAR) == IS_AGENTCORE_RUNTIME_VALUE

    def is_local(self) -> bool:
        return not (self._is_vercel or self._is_agentcore)

    def is_vercel(self) -> bool:
        return self._is_vercel

    def is_agentcore(self) -> bool:
        """Inside an Amazon Bedrock AgentCore Runtime (either of the two)."""
        return self._is_agentcore


runtime = Runtime()
