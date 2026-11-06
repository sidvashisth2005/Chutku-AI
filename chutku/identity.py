"""Who this assistant is, chosen once at install (owner, 2026-11-06: "everyone names their own AI").

Stored in `.env` in the install folder (KEY=VALUE lines, never committed; `.env.example` shows the keys). An environment
variable of the same name wins over the file. The defaults are the original Chutku, so an install without `.env`
behaves exactly as before.

    ASSISTANT_NAME      what she/he is called and answers to ("Oye <name>", "Hey <name>")
    ASSISTANT_GENDER    female | male | neutral       (grammar of her own Hindi: "kar rahi hoon" / "kar raha hoon")
    ASSISTANT_LANGUAGE  hinglish | english | hindi
    ASSISTANT_STYLE     warm | professional | witty | calm
    CHUTKU_RELAY_URL    the account relay the phone app also reaches (chutku/relay)
    CHUTKU_ACCOUNT_ID   the account ID (the password is never stored; the device token is in Credential Manager)
"""
from __future__ import annotations

import os
from pathlib import Path
import re

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
DEFAULTS = {"ASSISTANT_NAME": "Chutku", "ASSISTANT_GENDER": "female", "ASSISTANT_LANGUAGE": "hinglish",
            "ASSISTANT_STYLE": "warm", "CHUTKU_RELAY_URL": "", "CHUTKU_ACCOUNT_ID": ""}
CHOICES = {"ASSISTANT_GENDER": ("female", "male", "neutral"), "ASSISTANT_LANGUAGE": ("hinglish", "english", "hindi"),
           "ASSISTANT_STYLE": ("warm", "professional", "witty", "calm")}
NAME_RULE = re.compile(r"^[^\W\d_][\w .'-]{0,23}$")
_LINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$")


def _parse(path):
    values = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        found = _LINE.match(line)
        if found and not line.lstrip().startswith("#"):
            values[found.group(1)] = re.split(r"\s+#", found.group(2))[0].strip().strip("\"'")   # inline comment
    return values


def check(key, value):
    """The value, cleaned; ValueError for anything that is not allowed."""
    value = str(value).strip()
    if key == "ASSISTANT_NAME" and not NAME_RULE.fullmatch(value):
        raise ValueError("A name is 1-24 letters (spaces, ' - . allowed), starting with a letter.")
    if key in CHOICES and value.casefold() not in CHOICES[key]:
        raise ValueError(f"{key} must be one of: {', '.join(CHOICES[key])}.")
    if key == "CHUTKU_RELAY_URL" and value and not re.fullmatch(r"https?://[^\s/]+(?::\d+)?/?", value):
        raise ValueError("The relay address looks like https://relay.example.com (no path).")
    return value.casefold() if key in CHOICES else value.rstrip("/") if key == "CHUTKU_RELAY_URL" else value


def load(path=None) -> dict:
    values = dict(DEFAULTS)
    for key, value in _parse(path or ENV_PATH).items():
        if key in DEFAULTS:
            try:
                values[key] = check(key, value)
            except ValueError:
                pass   # a bad value keeps the default rather than breaking start-up
    for key in DEFAULTS:
        if os.environ.get(key):
            try:
                values[key] = check(key, os.environ[key])
            except ValueError:
                pass
    return values


def save(updates: dict, path=None) -> dict:
    """Write these keys into .env, keeping every other line (and comments) as they are."""
    path = Path(path or ENV_PATH)
    cleaned = {key: check(key, value) for key, value in updates.items() if key in DEFAULTS}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = ["# Chutku settings (made at install; `.venv\\Scripts\\python.exe -m chutku.cli setup` changes them)"]
    done = set()
    for index, line in enumerate(lines):
        found = _LINE.match(line)
        if found and found.group(1) in cleaned:
            lines[index] = f"{found.group(1)}={cleaned[found.group(1)]}"
            done.add(found.group(1))
    lines += [f"{key}={value}" for key, value in cleaned.items() if key not in done]
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return load(path)


def name() -> str:
    return load()["ASSISTANT_NAME"]


def gender() -> str:
    return load()["ASSISTANT_GENDER"]


SELF_FORMS = {
    "female": "When you speak Hindi or Hinglish about yourself, always use feminine forms: \"kar rahi hoon\", "
              "\"kar dungi\", \"samajh gayi\", \"main sakti hoon\", \"main ready hoon\"; never \"raha\", \"dunga\", "
              "\"gaya\", \"sakta\".",
    "male": "When you speak Hindi or Hinglish about yourself, always use masculine forms: \"kar raha hoon\", "
            "\"kar dunga\", \"samajh gaya\", \"main sakta hoon\".",
    "neutral": "Talk about yourself without gendered Hindi verb forms where you can (\"ho jayega\", \"main ready "
               "hoon\", \"karti/karta\" avoided).",
}
STYLES = {"warm": "warm, quick, witty, genuinely engaged, a thinking partner and a friend",
          "professional": "precise, calm and efficient, like a top executive assistant",
          "witty": "playful, quick and funny, but always useful",
          "calm": "gentle, patient and reassuring"}
LANGUAGES = {"hinglish": "in the same mix of Hindi and English the owner uses (Hinglish)",
             "english": "in clear, simple English", "hindi": "in Hindi (written in Roman letters)"}


def identity_line(values=None) -> str:
    """The first line of every prompt that writes the assistant's own words."""
    values = values or load()
    shown = "Chutku (छुटकू, said \"Chhutku\")" if values["ASSISTANT_NAME"] == "Chutku" else values["ASSISTANT_NAME"]
    kind = {"female": "female ", "male": "male ", "neutral": ""}[values["ASSISTANT_GENDER"]]
    return f"You are {shown}, the owner's {kind}AI companion. {SELF_FORMS[values['ASSISTANT_GENDER']]}"
