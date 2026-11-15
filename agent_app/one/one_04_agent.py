# -*- coding: utf-8 -*-

"""
The model and the agent's own tool, for the One class.

The agent itself is built per request in
:mod:`agent_app.runtimes.analytics_agent`; its data tools live on the MCP
server, :mod:`agent_app.runtimes.analytics_mcp`.
"""

import typing as T
from functools import cached_property

from strands import tool
from strands.models import BedrockModel

from ..paths import path_enum
from ..constants import LlmProviderEnum

if T.TYPE_CHECKING:  # pragma: no cover
    from .one_00_main import One


def load_strands_model_class(class_name: str, provider: str):
    """
    Import a strands model class, with an actionable error when its SDK is missing.

    Every provider SDK is a core dependency (see ``pyproject.toml``), so reaching
    the error path means the virtualenv is out of step with the lock file rather
    than that something is opt-in. ``strands.models`` lazy-imports each provider,
    so without this wrapper that surfaces as a bare ``ModuleNotFoundError: No
    module named 'anthropic'``, which does not say what to do about it.

    Args:
        class_name: The strands class to import, e.g. ``"AnthropicModel"``.
        provider: The ``LLM_PROVIDER`` value that asked for it.

    Returns:
        The strands model class.

    Raises:
        ImportError: If the provider's SDK is not importable.
    """
    from strands import models

    try:
        return getattr(models, class_name)
    except (AttributeError, ImportError) as e:
        raise ImportError(
            f"LLM_PROVIDER={provider!r} needs a vendor SDK that is not importable, "
            f"even though it is a core dependency. The virtualenv is probably "
            f"stale.\n"
            f"Reinstall with:\n"
            f"    mise run inst-python-deps\n"
            f"Or switch provider with LLM_PROVIDER in .env.defaults."
        ) from e


class AgentMixin:
    """Mixin providing the model of ``LLM_PROVIDER`` and the agent's own tool."""

    @cached_property
    def bedrock_model(self: "One") -> BedrockModel:  # pragma: no cover - needs AWS
        """Create a BedrockModel instance with configured model ID."""
        return BedrockModel(
            boto_session=self.boto_ses,
            model_id=self.config.model_id,
        )

    @cached_property
    def model(self: "One"):
        """
        Build the model for the provider selected by ``LLM_PROVIDER``.

        Exactly one provider is active per process. The credential check happens
        first so a missing API key fails here, with a readable message, rather
        than as an authentication error on the first user question.
        """
        self.config.validate()
        provider = self.config.llm_provider

        if provider == LlmProviderEnum.BEDROCK.value:
            return self.bedrock_model

        if provider == LlmProviderEnum.ANTHROPIC.value:
            anthropic_model_class = load_strands_model_class("AnthropicModel", provider)
            return anthropic_model_class(
                client_args={"api_key": self.config.anthropic_api_key},
                model_id=self.config.model_id,
                # max_tokens is required by the Anthropic provider, unlike the others.
                max_tokens=self.config.max_tokens,
            )

        if provider == LlmProviderEnum.OPENAI.value:
            # OpenAIResponsesModel targets /v1/responses, NOT /v1/chat/completions.
            # This matters: the reasoning models (gpt-5.x) refuse to combine
            # function tools with reasoning on the chat-completions endpoint --
            #     "Function tools with reasoning_effort are not supported for
            #      <model> in /v1/chat/completions. To use function tools, use
            #      /v1/responses or set reasoning_effort to 'none'."
            # This agent is nothing but tools, so the endpoint is the fix.
            # Setting reasoning_effort='none' would work too, but only for the
            # reasoning models -- the older ones reject the argument outright.
            # Responses is also OpenAI's current primary API, so this keeps
            # working across model generations.
            openai_model_class = load_strands_model_class(
                "OpenAIResponsesModel", provider
            )
            return openai_model_class(
                client_args={"api_key": self.config.openai_api_key},
                model_id=self.config.model_id,
            )

        if provider == LlmProviderEnum.GOOGLE.value:
            gemini_model_class = load_strands_model_class("GeminiModel", provider)
            return gemini_model_class(
                client_args={"api_key": self.config.google_api_key},
                model_id=self.config.model_id,
            )

        raise NotImplementedError(  # pragma: no cover
            f"No model builder for LLM_PROVIDER={provider!r}."
        )

    @tool(
        name="write_debug_report",
    )
    def tool_write_debug_report(
        self,
        content: str,
    ) -> str:
        """
        Write a debug report documenting the reasoning process and intermediate steps.

        This tool writes a markdown report to tmp/debug_report.md for debugging and
        transparency purposes. Use this to document your reasoning process.

        Args:
            content: The full markdown content to write to the debug report file.
                     Should include sections like:
                     - User Question
                     - Schema Analysis
                     - SQL Queries and Results
                     - Reasoning Steps
                     - Final Answer

        Returns:
            A confirmation message with the file path.
        """
        # Returned, never raised: a read-only filesystem (a deployed runtime)
        # must not end a turn whose answer is already written.
        try:
            path_enum.dir_tmp.mkdir(parents=True, exist_ok=True)
            path_enum.path_debug_report_md.write_text(content, encoding="utf-8")
        except OSError as e:
            return f"Debug report not written ({type(e).__name__}: {e}); carry on."
        return f"Debug report written to: {path_enum.path_debug_report_md}"
