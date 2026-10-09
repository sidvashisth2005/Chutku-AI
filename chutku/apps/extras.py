"""Small read-only app tools that return data (App Mastery A5+). Atlas actions only do things; these read things.

message.unread_count: how many WhatsApp chats are unread, read from the chat list's "Unread N" filter chip. Only a
number comes back (no names, no message text), so it neither taints nor exposes the session. Nothing is clicked and
no chat is opened, so nothing is marked read.
"""
from __future__ import annotations

import re

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

WHATSAPP = {"exe": "WhatsApp.Root.exe"}
LIST_AREA = [0, 0.1, 0.35, 0.3]   # the chat list's filter chips (All · Unread · Favourites · Groups)
_CHIP = re.compile(r"^\s*unread\s*(\d{1,4})?\s*$", re.I)

DRIVER = None   # tests set a fake Driver here


def unread_from(lines):
    """The number on the "Unread" chip (0 when the chip shows no number), or None when no chip is visible."""
    for line in lines:
        found = _CHIP.match(line["text"])
        if found:
            return int(found.group(1) or 0)
    return None


def _unread(arguments, _context):
    from chutku.apps.runner import Driver, _area
    import time
    driver = DRIVER or Driver()
    hwnd = driver.find_window(WHATSAPP)
    if hwnd is None:
        return ToolResult({"error": "WhatsApp is not open, so I cannot see the unread count."}, Verification.FAIL)
    driver.focus(hwnd)
    time.sleep(0.6)
    count = unread_from(driver.ocr(_area(driver.window_rect(hwnd), LIST_AREA)))
    if count is None:
        return ToolResult({"error": "The chat list's filters are not showing (a chat or panel may be covering it); "
                                    "I did not click anything."}, Verification.FAIL)
    return ToolResult({"app": "whatsapp", "unread_chats": count}, Verification.PASS)


def _validate_none(arguments):
    if arguments:
        raise ValueError("This tool takes no arguments.")


def say_unread(out):
    count = out.get("unread_chats")
    if count == 0:
        return "WhatsApp pe koi unread chat nahi hai."
    return f"WhatsApp pe {count} chats unread hain."


def register(registry):
    registry.register(Tool("message.unread_count", "How many WhatsApp chats are unread (a number only, read from "
                           "the chat list; nothing is opened or marked read)", Risk.OBSERVATION, _unread,
                           _validate_none, required_capability="desktop.input",
                           argument_schema={"type": "object", "properties": {}, "additionalProperties": False},
                           prerequisites=("WhatsApp Desktop open",), reversibility="not_applicable",
                           success_predicate="unread_chip_read"))
