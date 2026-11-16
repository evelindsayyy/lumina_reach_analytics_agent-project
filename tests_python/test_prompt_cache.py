# -*- coding: utf-8 -*-

"""
Prompt caching on the Anthropic API: which parts of a request are marked.
"""

from agent_app.prompt_cache import CACHE_CONTROL
from agent_app.prompt_cache import caching_model_class
from agent_app.prompt_cache import with_prompt_cache


def request(**overrides) -> dict:
    base = {
        "model": "claude-acme",
        "system": "You are the Acme analyst.",
        "tools": [{"name": "get_database_schema", "description": "d", "input_schema": {}}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "Which widget sells best?"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "rows"}]},
        ],
    }
    return {**base, **overrides}


class TestWithPromptCache:
    def test_the_system_prompt_is_cached_with_the_tools_before_it(self):
        """Anthropic caches the prefix up to a breakpoint: tools, then system."""
        system = with_prompt_cache(request())["system"]
        assert system == [{"type": "text", "text": "You are the Acme analyst.", "cache_control": CACHE_CONTROL}]

    def test_the_newest_block_is_cached_so_the_next_tool_round_reads_it(self):
        messages = with_prompt_cache(request())["messages"]
        assert messages[-1]["content"][-1]["cache_control"] == CACHE_CONTROL
        assert all("cache_control" not in b for m in messages[:-1] for b in m["content"])

    def test_at_most_two_breakpoints(self):
        """The API allows four; two cover the static prefix and the conversation."""
        marked = with_prompt_cache(request())
        blocks = marked["system"] + [b for m in marked["messages"] for b in m["content"]]
        assert sum("cache_control" in b for b in blocks) == 2

    def test_the_request_is_not_modified_in_place(self):
        original = request()
        with_prompt_cache(original)
        assert original == request()

    def test_nothing_to_mark_is_left_alone(self):
        bare = {"model": "m", "messages": [], "tools": []}
        assert with_prompt_cache(bare) == bare

    def test_plain_string_content_is_left_alone(self):
        plain = request(messages=[{"role": "user", "content": "q"}])
        assert with_prompt_cache(plain)["messages"] == plain["messages"]

    def test_an_already_marked_or_uncacheable_block_is_left_alone(self):
        marked = {"type": "text", "text": "q", "cache_control": {"type": "ephemeral", "ttl": "1h"}}
        thinking = {"type": "thinking", "thinking": "hmm", "signature": "s"}
        for block in (marked, thinking):
            out = with_prompt_cache(request(messages=[{"role": "user", "content": [block]}]))
            assert out["messages"][0]["content"] == [block]


class TestCachingModelClass:
    def test_wraps_the_strands_anthropic_request(self):
        from strands.models.anthropic import AnthropicModel

        model_class = caching_model_class(AnthropicModel)
        assert issubclass(model_class, AnthropicModel)
        assert model_class.__name__ == "CachingAnthropicModel"
        model = model_class(client_args={"api_key": "sk-test"}, model_id="claude-acme", max_tokens=100)
        formatted = model.format_request(
            [{"role": "user", "content": [{"text": "hi"}]}],
            system_prompt="You are the Acme analyst.",
        )
        assert formatted["system"][0]["cache_control"] == CACHE_CONTROL
        assert formatted["messages"][0]["content"][0]["cache_control"] == CACHE_CONTROL


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.prompt_cache",
        preview=False,
    )
