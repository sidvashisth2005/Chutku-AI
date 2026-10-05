"""One local log file for problems Chutku recovers from (data/logs/chutku.log, 5 x 2 MB, rotated).

Before this, about 40 places swallowed errors silently, so a broken Gemini, a crashed wake listener or a failed
spoken answer left no trace. The fallback behaviour is unchanged; only now it is written down. A redaction filter
keeps message text, typed text, phone numbers, tokens and keys out of the file.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import secrets
import threading

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_lock = threading.Lock()
_configured = False
_SENSITIVE = re.compile(r"""(["']?(?:text|content|message|arguments|phone|token|key|api_key|password)["']?\s*[:=]\s*)"""
                        r"""("[^"]*"|'[^']*'|[^\s,}]+)""", re.I)
_LONG_SECRET = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")
_PHONE = re.compile(r"\+?\d[\d \-]{8,16}\d")


def redact(text: str) -> str:
    text = _SENSITIVE.sub(lambda m: m.group(1) + "[REDACTED]", text)
    text = _LONG_SECRET.sub("[REDACTED]", text)
    return _PHONE.sub("[PHONE]", text)


class _Redact(logging.Filter):
    def filter(self, record):
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def _configure(base: Path | None = None):
    global _configured
    with _lock:
        if _configured:
            return
        directory = Path(base or _PROJECT_ROOT) / "data" / "logs"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(directory / "chutku.log", maxBytes=2_000_000, backupCount=5,
                                          encoding="utf-8", delay=True)
        except OSError:
            handler = logging.NullHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(_Redact())
        root = logging.getLogger("chutku")
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        root.propagate = False
        _configured = True


def get_logger(name: str) -> logging.Logger:
    """A logger under "chutku", writing to data/logs/chutku.log (tests write nowhere)."""
    from chutku.voice.heard import _under_test
    if _under_test():
        logger = logging.getLogger("chutku." + name)
        if not logging.getLogger("chutku").handlers:
            logging.getLogger("chutku").addHandler(logging.NullHandler())
            logging.getLogger("chutku").propagate = False
        return logger
    _configure()
    return logging.getLogger("chutku." + name)


def error_id() -> str:
    """A short id shown to the owner with an error and written next to its details in the log."""
    return secrets.token_hex(4)
