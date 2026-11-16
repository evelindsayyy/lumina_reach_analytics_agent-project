# -*- coding: utf-8 -*-

"""
Turning what the agent said into what the UI shows.

On the critical path of every reply, which is why it is not in
``agent_debugger.py`` -- that one only prints.

Strands does not hand back a clean answer. It hands back the message list it
built, thinking still inline as ``<thinking>`` tags, split across however many
messages the tool calls took. :func:`parse_agent_response` is the whole pipeline.
"""

import re

#: Fenced-block languages the chat UI renders as something other than code.
#: Each is also the tag name a model reaches for when it drifts from the fence.
#: One of the three halves of the rendering contract -- the others are the
#: lookup table in ``components/chat/blocks/index.ts`` and the instructions in
#: ``data/system-prompt.md``.
RENDERABLE_BLOCKS = ("chart", "mermaid")

_THINKING = r"<thinking>(.*?)</thinking>"


#: Tools the agent calls after it has answered. Text on either side of one of
#: these belongs to the same answer.
REPORTING_TOOLS = frozenset({"write_debug_report"})


def _add_answer_block(blocks: list[str], text: str) -> list[str]:
    """``blocks`` plus ``text``, without repeating what one already says."""
    if any(text in block for block in blocks):
        return blocks
    return [block for block in blocks if block not in text] + [text]


def extract_text_from_messages(messages: list, start_index: int = 0) -> str:
    """
    Collect thinking from every assistant message, plus the answer: all the
    text written after the last data tool call.

    **The answer can span several messages.** An agent often writes its
    answer (a chart, a table), calls ``write_debug_report``, then signs off
    with one more line or with nothing but ``<thinking>``. Reading only the
    final text lost the chart; reading the final message unconditionally
    yielded an empty answer, which the UI shows as a hang. Text before a data
    tool call (``execute_sql_query`` and the like) is narration, not answer,
    so each such call starts the answer afresh; if nothing follows the last
    one, the last text written is the answer.
    """
    all_thinking = []
    answer_blocks: list[str] = []
    last_text = None

    for msg in messages[start_index:]:
        if msg.get("role") != "assistant":
            continue
        for item in msg.get("content", []):
            if not isinstance(item, dict):
                continue
            tool_use = item.get("toolUse")
            if isinstance(tool_use, dict) and tool_use.get("name") not in REPORTING_TOOLS:
                answer_blocks = []
                continue
            if "text" not in item:
                continue
            text = item["text"]
            all_thinking.extend(
                m.strip() for m in re.findall(_THINKING, text, re.DOTALL) if m.strip()
            )
            stripped = re.sub(_THINKING, "", text, flags=re.DOTALL).strip()
            if stripped:
                last_text = stripped
                answer_blocks = _add_answer_block(answer_blocks, stripped)

    answer = "\n\n".join(answer_blocks) if answer_blocks else last_text
    texts = []
    if all_thinking:
        texts.append("<thinking>" + "\n\n".join(all_thinking) + "</thinking>")
    if answer:
        texts.append(answer)
    return "\n".join(texts)


def parse_response_text(full_text: str) -> tuple[str, str]:
    """
    Split text into (thinking, answer) by pulling out the ``<thinking>`` blocks.
    """
    thinking = "\n\n".join(
        m.strip() for m in re.findall(_THINKING, full_text, re.DOTALL)
    )

    answer = re.sub(_THINKING, "", full_text, flags=re.DOTALL)
    # A heading with nothing under it, left behind when the model streams a
    # section header and then puts the body inside a thinking block.
    answer = re.sub(r"^#{1,6}\s*$", "", answer, flags=re.MULTILINE)
    answer = re.sub(r"\n{3,}", "\n\n", answer)

    return thinking, answer.strip()


def normalize_render_blocks(text: str) -> str:
    """
    Rewrite ``<chart>``/``<mermaid>`` tag pairs into the fences the UI renders.

    The prompt asks for fences, but smaller models already emit ``<thinking>``
    tags and generalize the habit, wrapping a perfectly good chart payload in
    ``<chart>``. Markdown treats that as an unknown HTML tag and drops it, so the
    reply says "here is the chart" above nothing at all.

    Prompt wording alone does not survive a model that small and the mapping is
    unambiguous, so it is done mechanically. Content already inside a fence is
    left alone: the pattern requires the tag to sit on its own line.
    """
    for name in RENDERABLE_BLOCKS:
        pattern = rf"^[ \t]*<{name}>[ \t]*\n(.*?)\n[ \t]*</{name}>[ \t]*$"
        text = re.sub(
            pattern,
            lambda m, n=name: f"```{n}\n{m.group(1).strip()}\n```",
            text,
            flags=re.DOTALL | re.MULTILINE,
        )
    return text


def parse_agent_response(
    messages: list,
    start_index: int = 0,
) -> tuple[str, str]:
    """
    An agent's messages -> the (thinking, answer) pair the UI streams.

    The three steps are one function so a caller cannot run two of them and
    forget the third. Skipping the normalize step in particular fails silently:
    the answer still arrives, with the chart missing from it.
    """
    thinking, answer = parse_response_text(
        extract_text_from_messages(messages, start_index)
    )
    return thinking, normalize_render_blocks(answer)


#: Shown when the model provider refuses for capacity reasons (a rate or daily
#: token limit). Retrying later can work, so the message says so.
MODEL_THROTTLED_MESSAGE = (
    "The language model is over its usage limit right now, so I could not "
    "answer. Please try again later. If this keeps happening, the deployment "
    "needs a higher model quota or a different LLM_PROVIDER."
)

#: Shown when the agent cannot open its connection to the MCP server, so it
#: has no way to read the warehouse.
TOOLS_UNREACHABLE_MESSAGE = (
    "I could not reach the data tools service, so I could not look anything up. "
    "Please try again in a moment; if it keeps failing, the MCP runtime is down."
)

#: Shown for any other failure inside the agent turn. The details go to the
#: server log, not to the reader.
MODEL_FAILED_MESSAGE = (
    "Something went wrong while I was working on this, so I could not answer. "
    "Please try again; if it keeps failing, the server log has the details."
)


def agent_error_message(error: Exception) -> str:
    """
    The sentence to show the user when an agent turn raises.

    A turn that raises would otherwise reach the browser as a bare HTTP 500,
    which the chat UI renders as a broken turn with no explanation.
    """
    from strands.types.exceptions import MCPClientInitializationError
    from strands.types.exceptions import ModelThrottledException

    if isinstance(error, ModelThrottledException):
        return MODEL_THROTTLED_MESSAGE
    if isinstance(error, MCPClientInitializationError):
        return TOOLS_UNREACHABLE_MESSAGE
    return MODEL_FAILED_MESSAGE
