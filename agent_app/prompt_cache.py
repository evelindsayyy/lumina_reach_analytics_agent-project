# -*- coding: utf-8 -*-

"""
Prompt caching on the Anthropic API.

One question is several model calls: each tool round resends the system
prompt, the tool definitions and the whole conversation so far, including the
database schema the first tool returned. Without caching every resend is
billed in full, which is most of a question's cost. With two cache
breakpoints, a repeat costs a tenth of the input price:

- the system prompt, which caches everything before it too (the tools);
- the newest message block, so the next round reads the conversation so far.

The API ignores a breakpoint on a prefix shorter than the model's minimum, so
marking is always safe. Strands' ``AnthropicModel`` sends the system prompt as
a plain string and has no hook for this, so :func:`caching_model_class` wraps
its request builder.
"""

import typing as T

#: Anthropic's five-minute cache: long enough for the rounds of one question
#: and the follow-ups of one session.
CACHE_CONTROL = {"type": "ephemeral"}

#: The block types the API accepts a breakpoint on.
CACHEABLE_BLOCK_TYPES = frozenset({"text", "image", "document", "tool_use", "tool_result"})


def _mark(block: dict) -> dict:
    return {**block, "cache_control": CACHE_CONTROL}


def _with_cached_newest_block(messages: list[dict]) -> list[dict]:
    if not messages:
        return messages
    newest = messages[-1]
    content = newest.get("content")
    if not isinstance(content, list) or not content:
        return messages
    block = content[-1]
    if not isinstance(block, dict) or block.get("type") not in CACHEABLE_BLOCK_TYPES or "cache_control" in block:
        return messages
    return [*messages[:-1], {**newest, "content": [*content[:-1], _mark(block)]}]


def with_prompt_cache(request: dict) -> dict:
    """
    A copy of the Anthropic Messages ``request`` with its cache breakpoints
    set. The argument is not modified.
    """
    marked = dict(request)
    system = request.get("system")
    if isinstance(system, str) and system:
        marked["system"] = [_mark({"type": "text", "text": system})]
    if "messages" in request:
        marked["messages"] = _with_cached_newest_block(request["messages"])
    return marked


def caching_model_class(base: type) -> type:
    """
    A subclass of the Strands model class ``base`` whose requests carry the
    cache breakpoints of :func:`with_prompt_cache`.
    """

    class CachingModel(base):  # type: ignore[valid-type, misc]
        def format_request(self, *args: T.Any, **kwargs: T.Any) -> dict:
            return with_prompt_cache(super().format_request(*args, **kwargs))

    CachingModel.__name__ = CachingModel.__qualname__ = f"Caching{base.__name__}"
    return CachingModel
