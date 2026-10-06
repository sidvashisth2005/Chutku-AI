"""One Hinglish vocabulary for every instant parser (master plan S13).

Before, seven modules each had their own list of polite lead-ins and trailing fillers, so "bhai delete D:\\x.txt"
worked in one parser and not in another. Every parser now strips the same words.
"""
from __future__ import annotations

# Words that may open a request: "please", "oye chutku", "bhai", "yaar", "zara".
POLITE_WORDS = r"please|pls|plz|kindly|hey chutku|oye chutku|chutku|bhai|yaar|zara"
# Words that may close one: "... please", "... na", "... abhi", "... jaldi", "... for me".
TAIL_WORDS = r"please|pls|plz|for me|right now|now|jaldi|na|zara|abhi|bhai|yaar|chutku"

# Lead-ins inside a pattern that already starts with ^ (quick_intents) ...
POLITE = rf"(?:(?:{POLITE_WORDS})[,\s]+)*"
# ... and for parsers that use the prefix as the start of the pattern.
LEAD = "^" + POLITE
# The end of a request: optional fillers, then punctuation.
TAIL = rf"(?:[,\s]+(?:{TAIL_WORDS}))*[\s.!?]*$"

# A bare web address ("youtube.com", "https://x.com/abc").
import re as _re

DOMAIN = _re.compile(r"^(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?$", _re.IGNORECASE)
# Words that stand for "the message" itself, never its text ("send the message to mammi").
NO_TEXT = frozenset({"message", "a message", "the message", "msg", "a msg", "text", "a text", "it", "this", "that"})
