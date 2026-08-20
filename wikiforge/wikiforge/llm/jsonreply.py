"""Recover JSON from a model reply that is *mostly* JSON.

Models fence their JSON, preface it with "Here is the JSON:", or emit a trailing
comma. Rather than fail a pipeline stage on presentation, pull out the first
balanced object or array and parse that.
"""
import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class JSONReplyError(ValueError):
    pass


def parse_json_reply(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise JSONReplyError("The model returned nothing to parse.")

    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fall back to the first balanced {...} or [...] in the reply.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    candidate = text[start : index + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    raise JSONReplyError(f"No JSON could be recovered from: {text[:200]}")
