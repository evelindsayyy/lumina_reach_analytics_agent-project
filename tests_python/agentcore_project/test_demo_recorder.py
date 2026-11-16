# -*- coding: utf-8 -*-

"""
Recording the example questions' answers from the deployed agent: the parts
that need no AWS.
"""

import dataclasses
import json

import pytest

from agent_app.agentcore_project import demo_recorder as dr
from agent_app.paths import path_enum
from agent_app.runtimes import chat_turn


SITE_TOML = '''
[chat]
agent = "Acme Analyst"

[[chat.suggestedActions]]
render = "free"
title = "Introduction"
label = "What can you do?"
action = "What can you help me analyze?"

[[chat.suggestedActions]]
render = "table"
title = "Top Widgets"
label = "Which widgets sell?"
action = "List the ten best-selling widgets."
'''


def sse(*events) -> str:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"


class TestQuestions:
    def test_the_example_questions_of_site_toml(self):
        assert dr.example_questions(SITE_TOML) == [
            ("Introduction", "What can you help me analyze?"),
            ("Top Widgets", "List the ten best-selling widgets."),
        ]

    def test_the_shipped_site_has_examples(self):
        questions = dr.example_questions(path_enum.path_site_toml.read_text(encoding="utf-8"))
        assert len(questions) >= 4
        assert len({q for _, q in questions}) == len(questions)


class TestStream:
    def test_reasoning_and_answer_are_split(self):
        text = sse(
            {"type": "reasoning-start", "id": "r"},
            {"type": "reasoning-delta", "id": "r", "delta": "count "},
            {"type": "reasoning-delta", "id": "r", "delta": "rows"},
            {"type": "text-start", "id": "t"},
            {"type": "text-delta", "id": "t", "delta": "1,024 widgets."},
            {"type": "finish", "finishReason": "stop"},
        )
        assert dr.split_stream(text) == ("count rows", "1,024 widgets.")

    @pytest.mark.parametrize(
        "answer",
        [chat_turn.QUOTA_EXCEEDED_MESSAGE, chat_turn.USER_QUOTA_EXCEEDED_MESSAGE, chat_turn.EMPTY_ANSWER_MESSAGE, ""],
    )
    def test_a_refusal_or_failure_is_not_an_answer(self, answer):
        assert not dr.is_real_answer(answer)

    def test_a_real_answer_is(self):
        assert dr.is_real_answer("Widget A sold 1,024 units.")


def entry(question="List the ten best-selling widgets.", answer="a", recorded_at="2026-11-16"):
    return dr.RecordedAnswer(
        title="Top Widgets",
        question=question,
        reasoning="r",
        answer=answer,
        seconds=12.34,
        input_tokens=1500,
        output_tokens=300,
        recorded_at=recorded_at,
    )


class TestFile:
    def test_the_web_app_reads_camel_case(self):
        data = json.loads(dr.render_demo_answers("claude-acme", [entry()]))
        assert data["recordedAt"] == "2026-11-16"
        assert data["model"] == "claude-acme"
        assert data["answers"] == [
            {
                "title": "Top Widgets",
                "question": "List the ten best-selling widgets.",
                "reasoning": "r",
                "answer": "a",
                "seconds": 12.3,
                "inputTokens": 1500,
                "outputTokens": 300,
                "recordedAt": "2026-11-16",
            }
        ]

    def test_round_trip(self):
        text = dr.render_demo_answers("claude-acme", [entry()])
        assert dr.parse_demo_answers(text) == [dataclasses.replace(entry(), seconds=12.3)]
        assert dr.parse_demo_answers('{"recordedAt": "", "model": "", "answers": []}') == []

    def test_the_file_date_is_the_newest_recording(self):
        older = entry(question="q1", recorded_at="2026-11-01")
        data = json.loads(dr.render_demo_answers("m", [older, entry(question="q2")]))
        assert data["recordedAt"] == "2026-11-16"
        assert json.loads(dr.render_demo_answers("m", []))["recordedAt"] == ""


class TestMerge:
    QUESTIONS = [("A", "qa"), ("B", "qb"), ("C", "qc")]

    def test_a_rerecorded_answer_replaces_its_old_one_in_site_order(self):
        previous = [entry(question="qc", answer="old c"), entry(question="qa", answer="old a")]
        merged = dr.merge_answers(previous, [entry(question="qc", answer="new c")], self.QUESTIONS)
        assert [(e.question, e.answer) for e in merged] == [("qa", "old a"), ("qc", "new c")]

    def test_an_answer_to_a_question_no_longer_asked_is_dropped(self):
        merged = dr.merge_answers([entry(question="gone")], [entry(question="qb")], self.QUESTIONS)
        assert [e.question for e in merged] == ["qb"]

    def test_only_picks_questions_by_title(self):
        assert dr.select_questions(self.QUESTIONS, "") == self.QUESTIONS
        assert dr.select_questions(self.QUESTIONS, "b") == [("B", "qb")]
        with pytest.raises(ValueError, match="No example question titled"):
            dr.select_questions(self.QUESTIONS, "Z")

    def test_it_lives_with_the_site_copy(self):
        assert path_enum.path_demo_answers_json.parent == path_enum.dir_data


if __name__ == "__main__":
    from agent_app.tests import run_cov_test

    run_cov_test(
        __file__,
        "agent_app.agentcore_project.demo_recorder",
        preview=False,
    )
