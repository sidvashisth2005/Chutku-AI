"""Mic mute (owner, 2026-10-05): while showing Chutku to friends, their laughs and comments were heard mid-answer and
the answer stopped to take them in. Muting the mic keeps the conversation and Chutku's answer going while nothing from
the room is heard.

- Ctrl+Alt+M (anywhere) or the mic button on the HUD toggles it.
- While muted, the live conversation streams silence instead of the microphone, the wake listener and follow-up
  listening are off. Chutku keeps speaking.
- It is temporary: a new conversation or the end of one unmutes, and nothing is saved (a restart is always unmuted).
"""
from __future__ import annotations

import threading

_muted = threading.Event()


def muted():
    return _muted.is_set()


def set_muted(on):
    if on:
        _muted.set()
    else:
        _muted.clear()
    return muted()


def toggle():
    return set_muted(not muted())
