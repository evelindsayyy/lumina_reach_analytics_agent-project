# -*- coding: utf-8 -*-

"""
Tests for the model dispatch and the agent's own tool. The data tools are
tested with the MCP server, in ``tests_python/runtimes``.
"""

import pytest

from agent_app.one.one_00_main import one
from agent_app.paths import path_enum


class TestDebugReportTool:
    def test_write_debug_report(self):
        """The debug report tool writes the file and returns its path."""
        content = "# Debug Report\n\nHello from the test suite.\n"
        result = one.tool_write_debug_report(content=content)
        assert path_enum.path_debug_report_md.exists()
        assert path_enum.path_debug_report_md.read_text(encoding="utf-8") == content
        assert str(path_enum.path_debug_report_md) in result

    def test_deployed_the_report_goes_to_the_log(self, monkeypatch, capsys):
        """A runtime's code directory is read-only; its log (CloudWatch) is read."""
        from agent_app.runtime import runtime

        monkeypatch.setattr(runtime, "is_agentcore", lambda: True)
        result = one.tool_write_debug_report(content="# Report\nacme")
        assert result == "Debug report logged."
        assert "[debug_report]\n# Report\nacme" in capsys.readouterr().out


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.one.one_04_agent",
        preview=False,
    )


class TestLoadStrandsModelClass:
    """
    The lookup that turns a provider name into a strands class. No client is
    constructed, so no key and no network -- getattr on an already-imported
    module is the whole function.
    """

    def test_finds_a_shipped_class(self):
        from agent_app.one.one_04_agent import load_strands_model_class

        assert load_strands_model_class("BedrockModel", "bedrock").__name__ == (
            "BedrockModel"
        )

    def test_a_missing_class_names_the_extra_to_install(self):
        """
        The message has to say which extra, or the reader is left guessing which
        of four optional SDKs the failure is about.
        """
        from agent_app.one.one_04_agent import load_strands_model_class

        with pytest.raises(ImportError, match="anthropic"):
            load_strands_model_class("NoSuchModel", "anthropic")


class TestModelDispatch:
    """
    Which provider gets which strands class. Nothing is constructed for real:
    the loader is replaced, so this checks the branch mapping and the arguments
    each provider is handed -- the part that is this repo's code.

    Getting a branch wrong does not raise; it silently talks to the wrong
    vendor with the wrong key.
    """

    class FakeModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    @pytest.fixture
    def one_with(self, monkeypatch):
        from agent_app.config import Config
        from agent_app.one import one_04_agent
        from agent_app.one.one_00_main import One

        loaded = {}

        def fake_loader(class_name, provider):
            loaded["class_name"] = class_name
            loaded["provider"] = provider
            return TestModelDispatch.FakeModel

        monkeypatch.setattr(one_04_agent, "load_strands_model_class", fake_loader)

        def build(**config_kwargs):
            instance = One()
            instance.__dict__["config"] = Config(schema_name="acme_widgets", **config_kwargs)
            return instance, loaded

        return build

    def test_anthropic(self, one_with):
        one, loaded = one_with(llm_provider="anthropic", anthropic_api_key="k")
        model = one.model
        assert loaded["class_name"] == "AnthropicModel"
        assert model.kwargs["client_args"] == {"api_key": "k"}
        # Required by this provider and by no other.
        assert "max_tokens" in model.kwargs

    def test_openai_targets_the_responses_endpoint(self, one_with):
        """
        NOT OpenAIModel: the reasoning models refuse to combine function tools
        with reasoning on /v1/chat/completions, and this agent is nothing but
        tools.
        """
        one, loaded = one_with(llm_provider="openai", openai_api_key="k")
        model = one.model
        assert loaded["class_name"] == "OpenAIResponsesModel"
        assert model.kwargs["client_args"] == {"api_key": "k"}
        assert "max_tokens" not in model.kwargs

    def test_google(self, one_with):
        one, loaded = one_with(llm_provider="google", google_api_key="k")
        assert one.model.kwargs["client_args"] == {"api_key": "k"}
        assert loaded["class_name"] == "GeminiModel"

    def test_bedrock_takes_the_session_path(self, one_with, monkeypatch):
        """Bedrock authenticates with a session, so it skips the key branches."""
        one, _ = one_with(llm_provider="bedrock", aws_region="us-east-1")
        sentinel = object()
        monkeypatch.setitem(one.__dict__, "bedrock_model", sentinel)
        assert one.model is sentinel

    def test_a_missing_key_fails_before_any_request(self, one_with):
        """
        validate() runs first so the failure is readable here rather than an
        authentication error on the first user question.
        """
        one, _ = one_with(llm_provider="openai")
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            _ = one.model


class TestWriteDebugReportCreatesTmp:
    def test_missing_tmp_directory_is_created(self, monkeypatch, tmp_path):
        """
        A fresh checkout has no tmp/, and the first thing that writes there is
        this tool. Failing would lose the report the agent just wrote.
        """
        from agent_app.paths import path_enum

        missing = tmp_path / "not-created-yet"
        monkeypatch.setattr(path_enum, "dir_tmp", missing)
        monkeypatch.setattr(path_enum, "path_debug_report_md", missing / "debug_report.md")

        result = one.tool_write_debug_report(content="# Report")
        assert (missing / "debug_report.md").read_text() == "# Report"
        assert "debug_report.md" in result

    def test_an_unwritable_location_is_reported_not_raised(self, monkeypatch, tmp_path):
        """
        A deployed runtime may have a read-only filesystem. The report is a
        side note to an answer already written, so it must not end the turn.
        """
        from agent_app.paths import path_enum

        blocker = tmp_path / "a-file"
        blocker.write_text("not a directory")
        monkeypatch.setattr(path_enum, "dir_tmp", blocker)
        monkeypatch.setattr(path_enum, "path_debug_report_md", blocker / "debug_report.md")

        result = one.tool_write_debug_report(content="# Report")
        assert result.startswith("Debug report not written")
