"""Web requests that name a browser, plus the voice model's ways of saying them (owner session 2026-10-04):

    "open youtube.com in brave browser"                     -> web.open {url, browser: brave}
    "type "youtube.com" in Brave's address bar and press Enter" -> web.open {url, browser: brave}
    "search for "Latent season 2" on YouTube in Brave"      -> web.search {site: youtube, browser: brave}
    "play Latent season 2 latest episode on youtube in brave" -> youtube.play {browser: brave}
    "Brave mein YouTube kholo" / "chrome mein google kholo" -> web.open
    "open brave browser" / "brave browser kholo"            -> apps.launch Brave

Returns (tool, arguments, purpose, reply, finish) or None.
"""
from __future__ import annotations

import re

_NAMES = {"brave": "Brave", "chrome": "Chrome", "google chrome": "Chrome", "edge": "Edge", "microsoft edge": "Edge",
          "firefox": "Firefox"}
_B = r"(?P<b>brave|google chrome|chrome|microsoft edge|edge|firefox)"
_IN_BROWSER = re.compile(r"\s+(?:in|on|using|with|via)\s+(?:the\s+)?" + _B + r"(?:'s)?(?:\s+browser)?(?=\W|$)"
                         r"|\s+" + _B.replace("(?P<b>", "(?P<b4>") + r"(?:\s+browser)?\s+(?:mein|me|main|pe|par)(?=\W|$)"
                         r"|\s*" + _B.replace("(?P<b>", "(?P<b2>") + r"(?:\s+browser)?\s+(?:mein|me|main|pe|par)\s+", re.I)
_SITES = {"youtube": "https://www.youtube.com", "yt": "https://www.youtube.com", "google": "https://www.google.com",
          "gmail": "https://mail.google.com", "instagram": "https://www.instagram.com", "github": "https://github.com",
          "chatgpt": "https://chatgpt.com", "whatsapp web": "https://web.whatsapp.com", "netflix": "https://www.netflix.com",
          "amazon": "https://www.amazon.in", "flipkart": "https://www.flipkart.com", "linkedin": "https://www.linkedin.com",
          "twitter": "https://x.com", "x": "https://x.com", "facebook": "https://www.facebook.com", "maps": "https://maps.google.com"}
from chutku.intents.lexicon import DOMAIN as _DOMAIN
from chutku.intents.lexicon import LEAD as _P, TAIL as _T   # one Hinglish vocabulary for every parser
_Q = r"[\"'“”‘’]?"


def _clean_query(text):
    text = re.sub(r"^(?:for|about)\s+", "", text.strip(), flags=re.I)
    return text.strip(" \"'“”‘’.")


def _url(target):
    target = target.strip(" \"'“”‘’.").casefold()
    if target in _SITES:
        return _SITES[target]
    if _DOMAIN.match(target):
        return target if target.startswith(("http://", "https://")) else "https://" + target
    return None


def parse_browser(goal: str):
    text = " ".join(goal.split())
    # "open brave browser" / "brave browser kholo": the browser itself
    app = re.match(_P + r"(?:open|launch|start)\s+(?:the\s+)?" + _B + r"(?:\s+browser)?" + _T + "|"
                   + _P + _B.replace("(?P<b>", "(?P<b3>") + r"(?:\s+browser)?\s+(?:kholo|khol do|open karo|chalu karo)" + _T,
                   text, re.I)
    if app:
        name = _NAMES[(app.group("b") or app.group("b3")).casefold()]
        return "apps.launch", {"name": name}, f"Open {name}", f"Opened {name}.", True
    found = _IN_BROWSER.search(text)
    if not found:
        return None
    browser = (found.group("b") or found.group("b2") or found.group("b4")).casefold().split()[-1]
    rest = (text[:found.start()] + " " + text[found.end():]).strip()
    rest = re.sub(r"\s+'s address bar|\s+address bar", "", rest, flags=re.I)
    # type "youtube.com" (in the address bar) and press enter
    typed = re.match(_P + r"(?:type|enter|write|go to|open|visit|kholo)\s+" + _Q + r"(?P<t>[^\"'“”‘’]+?)" + _Q
                     + r"(?:\s+and\s+(?:press|hit)\s+enter)?" + _T, rest, re.I)
    hinglish_open = re.match(_P + r"(?P<t>[\w.\-/: ]+?)\s+(?:kholo|khol do|open karo|chalao|par jao|pe jao)" + _T, rest, re.I)
    for match in (typed, hinglish_open):
        if match and _url(match.group("t")):
            url = _url(match.group("t"))
            return ("web.open", {"url": url, "browser": browser}, f"Open {url} in {_NAMES[browser]}",
                    f"Opened {url} in {_NAMES[browser]}.", True)
    play = re.match(_P + r"(?:play|chalao|bajao|lagao)\s+(?P<q>.+?)\s+(?:on|in)\s+(?:youtube|yt)" + _T, rest, re.I) or \
        re.match(_P + r"(?:youtube|yt)\s+(?:pe|par|mein|me)\s+(?P<q>.+?)\s+(?:chalao|bajao|lagao|play karo|play)" + _T, rest, re.I)
    if play:
        query = _clean_query(play.group("q"))
        return ("youtube.play", {"query": query, "browser": browser}, f"Play {query} on YouTube in {_NAMES[browser]}",
                f"Started “{query}” on YouTube in {_NAMES[browser]}.", True)
    search = re.match(_P + r"(?:search|look up|find)\s+(?P<q>.+?)\s+(?:on|in)\s+(?P<site>youtube|yt|google)" + _T, rest, re.I) or \
        re.match(_P + r"(?:search|look up)\s+(?:on\s+)?(?P<site>youtube|yt|google)\s+(?:for\s+)?(?P<q>.+?)" + _T, rest, re.I) or \
        re.match(_P + r"(?P<site>youtube|yt|google)\s+(?:pe|par|mein|me)\s+(?P<q>.+?)\s+(?:search karo|search|dhundo)" + _T, rest, re.I) or \
        re.match(_P + r"(?:search|google)\s+(?P<q>.+?)" + _T, rest, re.I)
    if search:
        site = "youtube" if (search.groupdict().get("site") or "").casefold() in ("youtube", "yt") else "google"
        query = _clean_query(search.group("q"))
        if not query:
            return None
        label = "YouTube" if site == "youtube" else "Google"
        return ("web.search", {"query": query, "site": site, "browser": browser},
                f"Search {label} for {query} in {_NAMES[browser]}", f"Searched {label} for “{query}” in {_NAMES[browser]}.",
                True)
    return None
