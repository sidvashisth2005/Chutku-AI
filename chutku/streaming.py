"""Speak the first words of an answer while the rest is still being written (master plan S11).

The local model's answer pass is a JSON object {"answer": "..."} produced token by token. `AnswerSentences` reads
the answer text out of the partial JSON and hands each finished sentence to a callback. Every sentence passes the
same guards as the final reply before it is spoken (feminine forms; a claim no step performed stops the stream),
so streaming never says something the finished answer would have withheld.
"""
from __future__ import annotations

import json
import re

_START = re.compile(r'^\s*\{\s*"answer"\s*:\s*"')
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


def answer_prefix(partial_json):
    """The decoded text of the "answer" string so far (an unfinished escape at the end is left out)."""
    match = _START.match(partial_json)
    if not match:
        return ""
    raw = partial_json[match.end():]
    out, i = [], 0
    while i < len(raw):
        char = raw[i]
        if char == '"':
            break
        if char == "\\":
            if i + 1 >= len(raw):
                break   # the escape is not complete yet
            if raw[i + 1] == "u":
                if i + 6 > len(raw):
                    break
                try:
                    out.append(json.loads('"' + raw[i:i + 6] + '"'))
                except ValueError:
                    pass
                i += 6
                continue
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/"}.get(raw[i + 1], raw[i + 1]))
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


class AnswerSentences:
    """Feed the growing model output; finished, guarded sentences go to `say`. Stops for good on a bad sentence."""

    def __init__(self, say, guard=None):
        self.say, self.guard = say, guard or (lambda sentence: sentence)
        self.sent = 0          # characters of the answer already handed out
        self.spoken = []
        self.stopped = False

    def feed(self, partial_json, final=False):
        if self.stopped:
            return
        text = answer_prefix(partial_json)
        pending = text[self.sent:]
        parts = _SENTENCE_END.split(pending)
        complete = parts if final else parts[:-1]   # the last piece may still be growing
        for sentence in complete:
            self.sent += len(sentence)
            rest = text[self.sent:]
            self.sent += len(rest) - len(rest.lstrip())   # the space after it
            sentence = sentence.strip()
            if not sentence:
                continue
            guarded = self.guard(sentence)
            if guarded is None:
                self.stopped = True    # e.g. a claim no step did: speak nothing more of this answer
                return
            self.spoken.append(guarded)
            self.say(guarded)
