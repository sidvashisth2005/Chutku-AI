r"""Harvest each daily app's documentation (App Mastery A0): official pages first, then reputable guides.

Every source page is downloaded once as plain text into data/apps/<app>/sources/<n>.txt, with an index
(data/apps/<app>/sources/index.json: url, title, kind, fetched, characters, sha256, error). Chutku answers
"how do I ... in <app>" from these local copies (app.howto, A3) and the app atlases (A1+) cite them.

Usage: .venv\Scripts\python.exe scripts\app_docs.py [app ...]      (no app: all 11)
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

# kind: official (the maker's own docs), reference (a maintained list from a reputable site)
SOURCES = {
    "spotify": [
        ("official", "https://support.spotify.com/us/article/keyboard-shortcuts/"),
        ("official", "https://developer.spotify.com/documentation/web-api/concepts/spotify-uris-ids"),
        ("reference", "https://tutorialtactic.com/blog/spotify-shortcuts/"),
    ],
    "whatsapp": [
        ("reference", "https://noobspace.com/whatsapp-keyboard-shortcuts-for-desktop/"),
        ("reference", "https://tutorialtactic.com/blog/whatsapp-desktop-shortcuts/"),
        ("reference", "https://www.webnots.com/whatsapp-keyboard-shortcuts-for-desktop-apps-windows-and-mac/"),
    ],
    "brave": [
        ("official", "https://support.google.com/chrome/answer/157179?hl=en&co=GENIE.Platform%3DDesktop"),
        ("official", "https://support.google.com/youtube/answer/7631406?hl=en"),
        ("reference", "https://tutorialtactic.com/blog/brave-browser-shortcuts/"),
        ("reference", "https://www.stefanjudis.com/today-i-learned/how-to-find-all-internal-pages-in-chromiums-and-firefox/"),
    ],
    "vscode": [
        ("official", "https://code.visualstudio.com/docs/configure/command-line"),
        ("official", "https://code.visualstudio.com/docs/editing/getting-started/tips-and-tricks"),
        ("official", "https://code.visualstudio.com/docs/configure/keybindings"),
    ],
    "settings": [
        ("official", "https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings"),
        ("official", "https://support.microsoft.com/en-us/windows/keyboard-shortcuts-in-windows-dcc61a57-8ff0-cffe-9796-cb9706c75eec"),
    ],
    "chatgpt": [
        ("reference", "https://windowsforum.com/news/chatgpt-windows-11-app-guide-store-install-alt-space-companion-winget-options.414512/"),
        ("reference", "https://chatai.guide/features/chatgpt-windows-app/"),
        ("reference", "https://www.webnots.com/10-tips-to-use-chatgpt-windows-app/"),
    ],
    "discord": [
        ("reference", "https://www.hongkiat.com/blog/keyboard-shortcuts-discord/"),
        ("reference", "https://gist.github.com/ghostrider-05/8f1a0bfc27c7c4509b4ea4e8ce718af0"),
        ("official", "https://support.discord.com/hc/en-us/articles/225977308-Keyboard-Shortcuts"),
    ],
    "vlc": [
        ("official", "https://wiki.videolan.org/Documentation:Command_line"),
        ("official", "https://wiki.videolan.org/Documentation:Modules/hotkeys/"),
        ("reference", "https://www.ditig.com/vlc-cheat-sheet"),
    ],
    "telegram": [
        ("official", "https://core.telegram.org/api/links"),
        ("reference", "https://winaero.com/telegram-desktop-keyboard-shortcuts/"),
        ("reference", "https://usethekeyboard.com/telegram/"),
    ],
    "explorer": [
        ("official", "https://support.microsoft.com/en-us/windows/keyboard-shortcuts-in-windows-dcc61a57-8ff0-cffe-9796-cb9706c75eec"),
        ("reference", "https://www.itechguides.com/keyboard-shortcuts-for-file-explorer-in-windows-11/"),
        ("reference", "https://www.elevenforum.com/t/list-of-shell-commands-in-windows-11.1080/"),
    ],
    "notepad": [
        ("reference", "https://qwerty.school/hotkeys/windows-notepad"),
        ("reference", "https://www.anoopcnair.com/latest-features-of-notepad-in-windows-11/"),
    ],
}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chutku-docs/1.0"


def page_text(raw: str) -> tuple[str, str]:
    """(title, readable text) from HTML: scripts/styles/navigation dropped, block tags become line breaks."""
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    raw = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|section|article|table|ul|ol|dt|dd|pre)>", "\n", raw)
    raw = re.sub(r"(?i)<(td|th)\b[^>]*>", " | ", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return (html.unescape(" ".join(title.group(1).split())) if title else ""), text


def fetch(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(3_000_000).decode(response.headers.get_content_charset() or "utf-8", "replace")


def harvest(app: str, sources=None, base: Path = ROOT, fetcher=fetch) -> list[dict]:
    folder = base / "data" / "apps" / app / "sources"
    folder.mkdir(parents=True, exist_ok=True)
    index = []
    for number, (kind, url) in enumerate(sources or SOURCES[app], 1):
        entry = {"n": number, "url": url, "kind": kind, "fetched": datetime.now().isoformat(timespec="seconds")}
        try:
            title, text = page_text(fetcher(url))
            if len(text) < 300:
                raise ValueError("page had almost no readable text (blocked or script-only)")
            (folder / f"{number}.txt").write_text(f"{title}\n{url}\n\n{text}", encoding="utf-8")
            entry |= {"title": title, "characters": len(text),
                      "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
        except (OSError, ValueError, urllib.error.URLError) as error:
            entry["error"] = f"{type(error).__name__}: {str(error)[:160]}"
        index.append(entry)
        time.sleep(0.5)   # polite to the sites
    (folder / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    return index


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    apps = argv or list(SOURCES)
    unknown = [a for a in apps if a not in SOURCES]
    if unknown:
        raise SystemExit(f"Unknown app(s): {unknown}. Known: {', '.join(SOURCES)}")
    total = ok = 0
    for app in apps:
        for entry in harvest(app):
            total += 1
            ok += "error" not in entry
            status = f"{entry['characters']:>7} chars" if "error" not in entry else entry["error"]
            print(f"{app:9s} {entry['kind']:9s} {status:40s} {entry['url']}")
    print(f"{ok}/{total} pages saved under data\\apps\\<app>\\sources")
    return ok, total


if __name__ == "__main__":
    main(sys.argv[1:])
