# -*- coding: utf-8 -*-

"""
Tests for splitting an agent turn into reasoning and answer.

These run on hand-built message lists rather than a live agent: the shapes that
break the split are exactly the ones that are hard to provoke on demand from a
real model, so they are written out literally here.
"""

from agent_app.agent_response import extract_text_from_messages
from agent_app.agent_response import normalize_render_blocks
from agent_app.agent_response import parse_agent_response
from agent_app.agent_response import parse_response_text


def _assistant(text: str) -> dict:
    return {"role": "assistant", "content": [{"text": text}]}


def _user(text: str) -> dict:
    return {"role": "user", "content": [{"text": text}]}


class TestExtractTextFromMessages:
    def test_answer_in_final_message(self):
        """The ordinary shape: the last assistant message carries the answer."""
        messages = [
            _user("how many rows?"),
            _assistant("<thinking>need the schema</thinking>"),
            _user("<tool result>"),
            _assistant("<thinking>counted them</thinking>\n\nThere are 12 rows."),
        ]
        thinking, answer = parse_response_text(extract_text_from_messages(messages))
        assert "need the schema" in thinking
        assert "counted them" in thinking
        assert answer == "There are 12 rows."

    def test_answer_survives_a_pure_thinking_sign_off(self):
        """
        An agent that answers, writes a debug report, then signs off with nothing
        but <thinking> must still produce an answer.

        Reading the final message unconditionally returned an empty string here,
        and the chat UI rendered a reasoning block with no reply underneath --
        indistinguishable, from the user's side, from a hang.
        """
        messages = [
            _user("which records look wrong?"),
            _assistant("<thinking>need the schema</thinking>"),
            _user("<tool result>"),
            _assistant("<thinking>query returned rows</thinking>\n\n- row 7: -35.1%"),
            _user("<tool result: debug report written>"),
            _assistant("<thinking>The final answer has been provided to the User.</thinking>"),
        ]
        thinking, answer = parse_response_text(extract_text_from_messages(messages))
        assert answer == "- row 7: -35.1%"
        assert "The final answer has been provided" in thinking

    def test_thinking_only_turn_yields_no_answer(self):
        """With no answer text anywhere, there is genuinely nothing to return."""
        messages = [
            _user("hello"),
            _assistant("<thinking>nothing to say</thinking>"),
        ]
        thinking, answer = parse_response_text(extract_text_from_messages(messages))
        assert thinking == "nothing to say"
        assert answer == ""

    def test_start_index_skips_earlier_turns(self):
        """Only messages from start_index onward count toward this turn."""
        messages = [
            _user("first question"),
            _assistant("<thinking>old</thinking>\n\nOld answer."),
            _user("second question"),
            _assistant("<thinking>new</thinking>\n\nNew answer."),
        ]
        thinking, answer = parse_response_text(extract_text_from_messages(messages, 2))
        assert thinking == "new"
        assert answer == "New answer."


def _assistant_then_tool(text: str, tool: str) -> dict:
    return {"role": "assistant", "content": [{"text": text}, {"toolUse": {"name": tool, "input": {}}}]}


class TestAnswerSpansTheReportCall:
    """
    Found in a recorded answer: the agent wrote its chart, called
    write_debug_report, then signed off with one line. Keeping only the last
    text lost the chart ("Line chart delivered", said the report).
    """

    CHART = "```chart\n{\"type\": \"line\"}\n```"

    def test_text_before_and_after_the_report_call_is_one_answer(self):
        messages = [
            _user("CPA per day as a line chart?"),
            _assistant_then_tool("Let me look at the schema.", "get_database_schema"),
            _user("<schema>"),
            _assistant_then_tool("Now the daily CPA.", "execute_sql_query"),
            _user("<rows>"),
            _assistant_then_tool(f"Daily CPA:\n\n{self.CHART}", "write_debug_report"),
            _user("<report written>"),
            _assistant("CPA is flat."),
        ]
        _, answer = parse_agent_response(messages)
        assert answer == f"Daily CPA:\n\n{self.CHART}\n\nCPA is flat."

    def test_narration_before_the_last_query_is_not_the_answer(self):
        messages = [
            _assistant_then_tool("I will check the schema first.", "get_database_schema"),
            _user("<schema>"),
            _assistant_then_tool("Querying now.", "execute_sql_query"),
            _user("<rows>"),
            _assistant("There are 12 rows."),
        ]
        assert parse_agent_response(messages)[1] == "There are 12 rows."

    def test_a_restated_answer_is_not_repeated(self):
        messages = [
            _assistant_then_tool("There are 12 rows.", "write_debug_report"),
            _user("<report written>"),
            _assistant("There are 12 rows.\n\nAll of them are active."),
        ]
        assert parse_agent_response(messages)[1] == "There are 12 rows.\n\nAll of them are active."

    def test_a_sign_off_already_in_the_answer_is_dropped(self):
        messages = [
            _assistant_then_tool("There are 12 rows. All of them are active.", "write_debug_report"),
            _user("<report written>"),
            _assistant("All of them are active."),
        ]
        assert parse_agent_response(messages)[1] == "There are 12 rows. All of them are active."

    def test_a_final_query_with_nothing_after_it_keeps_the_last_text(self):
        """The old fallback: better the last words than nothing."""
        messages = [_assistant_then_tool("Here is what I found so far.", "execute_sql_query"), _user("<rows>")]
        assert parse_agent_response(messages)[1] == "Here is what I found so far."


class TestToolBlocksAreSkipped:
    def test_tool_use_and_result_blocks_are_ignored(self):
        """
        A turn that calls a tool has content items that are not text at all.
        Reading them as text would raise; there is a guard, and this is it.
        """
        messages = [
            {
                "role": "assistant",
                "content": [
                    {"text": "<thinking>let me query</thinking>"},
                    {"toolUse": {"name": "execute_sql_query", "input": {"sql": "SELECT 1"}}},
                ],
            },
            {
                "role": "user",
                "content": [{"toolResult": {"content": [{"text": "| n |"}]}}],
            },
            _assistant("Here is the count."),
        ]
        thinking, answer = parse_agent_response(messages)
        assert thinking == "let me query"
        assert answer == "Here is the count."


class TestNormalizeRenderBlocks:
    def test_chart_tag_becomes_a_fence(self):
        """
        Nova Lite wraps chart payloads in <chart>, generalizing from <thinking>.
        Markdown drops the unknown tag, so the reply announces a chart that is
        not there. Re-fence it.
        """
        text = (
            "<chart>\n"
            '{"type": "bar", "title": "Totals", "categories": ["a"], '
            '"series": [{"name": "x", "values": [1]}]}\n'
            "</chart>\n\n"
            "Here is the chart."
        )
        out = normalize_render_blocks(text)
        assert out.startswith("```chart\n")
        assert "```\n\nHere is the chart." in out
        assert "<chart>" not in out

    def test_mermaid_tag_becomes_a_fence(self):
        text = "<mermaid>\nflowchart LR\n    A --> B\n</mermaid>"
        out = normalize_render_blocks(text)
        assert out == "```mermaid\nflowchart LR\n    A --> B\n```"

    def test_existing_fence_is_untouched(self):
        text = '```chart\n{"type": "bar"}\n```'
        assert normalize_render_blocks(text) == text

    def test_plain_prose_is_untouched(self):
        text = "One group accounts for 40% of the problem records."
        assert normalize_render_blocks(text) == text

class TestAgentErrorMessage:
    def test_throttling_says_try_later(self):
        from strands.types.exceptions import ModelThrottledException

        from agent_app.agent_response import MODEL_THROTTLED_MESSAGE, agent_error_message

        assert agent_error_message(ModelThrottledException("Too many tokens per day")) == MODEL_THROTTLED_MESSAGE

    def test_anything_else_hides_the_details(self):
        from agent_app.agent_response import MODEL_FAILED_MESSAGE, agent_error_message

        message = agent_error_message(RuntimeError("secret internal detail"))
        assert message == MODEL_FAILED_MESSAGE
        assert "secret" not in message


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.agent_debugger",
        preview=False,
    )


class TestParseResponseText:
    def test_splits_thinking_from_answer(self):
        thinking, answer = parse_response_text(
            "<thinking>Let me check</thinking>The answer is 42."
        )
        assert thinking == "Let me check"
        assert answer == "The answer is 42."

    def test_several_blocks_are_joined(self):
        thinking, _ = parse_response_text("<thinking>a</thinking>x<thinking>b</thinking>")
        assert thinking == "a\n\nb"

    def test_no_thinking_leaves_the_answer_whole(self):
        assert parse_response_text("plain answer") == ("", "plain answer")

    def test_orphaned_heading_is_dropped(self):
        """
        A header whose body ended up inside a thinking block would otherwise
        render as a bare "##" line above nothing.
        """
        _, answer = parse_response_text("## \n<thinking>the body</thinking>\nreal text")
        assert "##" not in answer
        assert answer == "real text"

    def test_blank_runs_are_collapsed(self):
        _, answer = parse_response_text("a\n\n\n\n\nb")
        assert answer == "a\n\nb"


class TestParseAgentResponse:
    """
    The three steps as one call, because a caller that runs two of them and
    forgets the third fails silently -- the answer arrives with the chart gone.
    """

    def test_end_to_end(self):
        messages = [
            _assistant("<thinking>picking a chart</thinking>Here is the trend:"),
            _assistant("<chart>\n{\"type\": \"bar\"}\n</chart>"),
        ]
        thinking, answer = parse_agent_response(messages)
        assert thinking == "picking a chart"
        # the intro and the chart are one answer, the chart tag now a fence
        assert answer == 'Here is the trend:\n\n```chart\n{"type": "bar"}\n```'

    def test_normalizes_what_the_two_step_path_would_miss(self):
        """This is the step the debug path used to skip."""
        messages = [_assistant("<mermaid>\ngraph TD;\n</mermaid>")]
        _, answer = parse_agent_response(messages)
        assert answer.startswith("```mermaid")

    def test_start_index_is_passed_through(self):
        messages = [_assistant("old answer"), _user("new q"), _assistant("new answer")]
        assert parse_agent_response(messages, 1)[1] == "new answer"
