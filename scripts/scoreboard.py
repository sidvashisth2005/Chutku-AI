"""20x plan scoreboard: the owner's burden per 100 requests (B100), from Chutku's own logs. No network, no model.

    python scripts/scoreboard.py [--days 7] [--base D:/Project/Chutku]

B100 = per 100 action requests: 5 x failed or given up, 3 x complained-about (wrong action), 2 x each question or
approval the owner had to answer, 1 x each 5 s waited beyond 5 s, 20 x each hang. See docs/TWENTY_X_PLAN.md.
"""
import argparse
import collections
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

COMPLAINT = re.compile(r"\b(?:galat|wrong|nahi hua|not working|kaam nahi|bakwas|ye nahi|yeh nahi|not this|"
                       r"phir se|dobara|again|kyu nahi|why didn'?t)\b", re.I)
FAILED = {"failed", "cancelled", "stopped"}
TEST_AREAS = re.compile(r"Chutku(?:Scratch|Practice)", re.I)

# A spoken line that promises PC work ("kar rahi hoon", "bhej dungi", "ho gaya"). In a voice conversation such a line
# is fine only when a task row backs it; without one it is a promise Chutku never kept (pillar 6: never lies).
_VERB = r"(?:kar|bhej|khol|laga|chala|ban|dhundh|likh|set kar|band kar|open kar|play kar|yaad dila)"
PROMISE = re.compile(rf"\b{_VERB}\w*\s+(?:rahi|raha|rahe)\s+h(?:oo|u)n\b|\b{_VERB}\w*\s+(?:dungi|dunga|deti hoon|"
                     rf"deta hoon|diya|di)\b|\bho (?:gaya|gayi|jayega|jaega)\b", re.I)
# Chit-chat question tails that add nothing (213 of 873 replies ended in "?" by 2026-11-10, most like these). A real
# question the flow needs ("haan ya na?", "what should I send?") is not a tail.
TAIL = re.compile(r"(?:aur kuch|kuch aur|kya kehte ho|kya bolte ho|kuch help chahiye|kuch kaam (?:hai|karna)|"
                  r"tum sunao|bolo bolo|kya chal raha hai|koi task karwana|help kar sakti)[^.!?]*\?\s*$", re.I)
CANNOT = re.compile(r"nahi\s+(?:\w+\s+){0,2}sakti|can'?t|cannot|mera control nahi", re.I)

# The Daily 30: the request families an ordinary user makes every day. A tool name decides first; for a turn without
# tools (a clarify or a failure before any step) the words decide. Everything else is "other".
FAMILIES = [
    ("whatsapp_send", r"^message\.send$", r"\b(?:send|bhej\w*)\b.*\b(?:whatsapp|chat|ko)\b|\bwhatsapp\b.*\b(?:send|bhej\w*)\b"),
    ("whatsapp_read", r"^message\.(?:read|unread|last)|^app\.whatsapp\.show", r"\b(?:read|padh\w*|unread|last message)\b.*\b(?:whatsapp|chat)\b"),
    ("whatsapp_open_chat", r"^message\.open_chat$|^app\.whatsapp\.", r"\bchat\b"),
    ("music_play", r"^app\.spotify\.play|^spotify\.|^youtube\.play$", r"\b(?:play|chalao|chala|gaana|gaane|song|playlist|spotify|youtube)\b"),
    ("media_control", r"^media\.control$|^app\.spotify\.(?:pause|next|previous|volume)|^app\.brave\.yt_", r"\b(?:pause|resume|next|skip|aage|peeche|roko)\b"),
    ("volume", r"^audio\.|^system\.volume", r"\b(?:volume|awaaz|mute|unmute)\b"),
    ("bluetooth_wifi", r"bluetooth|^network\.|^net\.|wifi", r"\b(?:bluetooth|wi-?fi|internet|hotspot)\b"),
    ("browser", r"^app\.brave\.|^browser\.|^web\.open$", r"\b(?:tab|brave|chrome|edge|browser|site|url|page)\b"),
    ("open_app", r"^apps\.launch$|^app\.\w+\.open$", r"\b(?:open|kholo|khol|chalu|launch|start)\b"),
    ("close_switch_app", r"^apps\.(?:quit|close|focus)$|^windows\.", r"\b(?:close|band|quit|switch|minimi[sz]e|window)\b"),
    ("web_search", r"^web\.(?:search|results|read)$|^task\.delegate$", r"\b(?:search|google|dhundo|research)\b"),
    ("weather_news", r"^web\.(?:weather|news)$", r"\b(?:weather|mausam|news|khabar)\b"),
    ("time_date", r"^system\.get_time$", r"\b(?:time|date|samay|tarikh|baje)\b"),
    ("reminders", r"^reminder\.|^task\.(?:schedule|list|cancel)$", r"\b(?:remind|yaad|alarm|timer|schedule|har roz)\b"),
    ("files_write", r"^filesystem\.(?:write|create|move|copy|rename|organize)|^note\.|^documents\.", r"\b(?:write|likho|note|save|move|rename|organi[sz]e)\b"),
    ("files_find_open", r"^files\.|^filesystem\.(?:list|search|largest|open)|^file\.", r"\b(?:file|folder|pdf|video|photo|download|recent|kholo)\b"),
    ("screen", r"^screen\.|^desktop\.", r"\b(?:screen|visible|dikh|on the screen)\b"),
    ("type_keys", r"^keyboard\.|^input\.|^mouse\.", r"\b(?:type|press|click|enter|key)\b"),
    ("system_info", r"^system\.(?:disk|performance|gpu|environment)|^apps\.installed$", r"\b(?:disk|space|ram|cpu|installed|battery)\b"),
    ("power", r"^power\.", r"\b(?:shutdown|restart|reboot|sleep|hibernate|band kar)\b"),
    ("settings", r"^settings\.(?!timeline|offline)|^app\.settings\.|^registry\.|^startup\.", r"\b(?:setting|theme|dark mode|brightness|night light)\b"),
    ("install", r"^apps\.(?:install|uninstall)$", r"\b(?:install|uninstall)\b"),
    ("memory", r"^memory\.|^mind\.|^history\.|^me\.", r"\b(?:remember|yaad rakh|forget|who is|kaun)\b"),
    ("build_code", r"^code\.", r"\b(?:build|code|app bana|program)\b"),
    ("help_howto", r"^apps\.howto$|^help", r"\b(?:how do i|kaise|help|what can you)\b"),
    ("other_messaging", r"^telegram\.|^email\.", r"\b(?:telegram|email|mail)\b"),
    ("chutku_control", r"^(?:settings\.(?:timeline|offline)|nightshift|rewind|remote|never|reflex|ledger|evolve|skill|backup)\.", r"\b(?:timeline|offline|rewind|phone|pair|never rule)\b"),
]
_FAMILY_TOOL = [(name, re.compile(tool)) for name, tool, _ in FAMILIES]
_FAMILY_WORDS = [(name, re.compile(words, re.I)) for name, _, words in FAMILIES]


def family(said, tools=(), status="done"):
    """The Daily-30 family of one request: by its first matching tool when the request finished (an unfinished one
    lists only the steps that got done, e.g. the launch before a cancelled play), else by its words, else 'other'."""
    for tool in (tools or ()) if status == "done" else ():
        for name, pattern in _FAMILY_TOOL:
            if pattern.search(str(tool)):
                return name
    for name, pattern in _FAMILY_WORDS:
        if pattern.search(said or ""):
            return name
    return "other"


def unbacked_promises(turns):
    """Voice chat lines that promise PC work with no task row in that conversation (an estimate: the chat lines of a
    conversation are all logged at its end, so a conversation is a run of 'said' rows with the same time stamp, and
    its tasks are the voice task rows logged since the previous conversation ended)."""
    said = sorted((r for r in turns if r.get("origin") == "voice" and r.get("status") == "said"), key=lambda r: r["at"])
    tasks = sorted(r["at"] for r in turns if r.get("origin") == "voice" and r.get("status") != "said")
    blocks, previous = [], None
    for row in said:
        if previous is None or row["at"] - previous > 10:
            blocks.append([])
        blocks[-1].append(row)
        previous = row["at"]
    total, examples, last_end = 0, [], float("-inf")
    for index, block in enumerate(blocks):
        # A conversation's tasks are logged while it runs, i.e. before its chat lines (written when it ends); one still
        # running at the end is logged a little later (live 2026-11-06: 69 s), so add a 3-minute grace, never past
        # the next conversation's chat lines.
        later = blocks[index + 1][0]["at"] if index + 1 < len(blocks) else float("inf")
        end = min(block[-1]["at"] + 180, later)
        kept = [r for r in block if PROMISE.search(r.get("reply", "")) and not CANNOT.search(r.get("reply", ""))
                and not r.get("reply", "").rstrip(" .!\"'").endswith("?")]
        if any("task" in r for r in block):   # logged since 2026-11-10: each turn says whether it started a task
            exact = [r for r in kept if not r.get("task")]
            total += len(exact)
            examples += [r["reply"][:80] for r in exact]
            last_end = end
            continue
        backed = sum(last_end < at <= end for at in tasks)
        missing = max(0, len(kept) - backed)
        total += missing
        examples += [r["reply"][:80] for r in kept[len(kept) - missing:]]   # tasks pair with the earliest promises
        last_end = end
    return total, examples[:5]


def _jsonl(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def score(base, days=7, now=None):
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    turns = [r for r in _jsonl(base / "data" / "conversations.jsonl")
             if r.get("origin") != "script" and datetime.fromtimestamp(r.get("at", 0), timezone.utc) >= since]
    actions = [r for r in turns if r.get("status") != "said"]          # "said" = chat in a voice conversation
    failed = sum(r.get("status") in FAILED for r in actions)
    clarify = sum(r.get("status") == "clarify" for r in actions)
    complaints = sum(1 for before, after in zip(turns, turns[1:])
                     if after.get("at", 0) - before.get("at", 0) <= 180 and COMPLAINT.search(after.get("said", "")))
    log = [r for r in _jsonl(base / "data" / "actions.log.jsonl")
           if datetime.fromisoformat(r.get("time", "1970-01-01T00:00:00+00:00")) >= since
           and not TEST_AREAS.search(json.dumps(r.get("arguments") or {}))]   # live-check scripts, not the owner
    approvals = sum(r.get("state") == "WAITING_CONFIRMATION" for r in log)
    hangs = [p.name for p in (base / "data" / "logs").glob("hang-*.txt")
             if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) >= since]
    timed = sorted(r["seconds"] for r in actions if isinstance(r.get("seconds"), (int, float)))
    waited = sum(max(0.0, s - 5.0) / 5.0 for s in timed)
    lies, lie_examples = unbacked_promises(turns)
    tails = sum(bool(TAIL.search(r.get("reply") or "")) for r in turns)
    burden = 5 * (failed + lies) + 3 * complaints + 2 * (clarify + approvals) + waited + 20 * len(hangs)
    families = collections.defaultdict(collections.Counter)
    for r in actions:
        families[family(r.get("said"), r.get("tools"), r.get("status"))][r.get("status")] += 1
    daily = sorted(((name, c["done"], sum(c.values()), dict(c)) for name, c in families.items()),
                   key=lambda item: (item[1] - item[2], item[1] / item[2]))   # most unfinished requests first
    tools = collections.defaultdict(collections.Counter)
    for row in log:
        tools[row.get("tool")][row.get("state")] += 1
    worst = sorted(((name, c) for name, c in tools.items() if sum(c.values()) >= 3),
                   key=lambda item: (item[1]["COMPLETED"] / sum(item[1].values()), -sum(item[1].values())))[:12]
    tiers = collections.Counter("+".join(sorted(set(r.get("planners") or ["?"]))) for r in actions)

    def pct(q):
        return round(timed[min(len(timed) - 1, int(len(timed) * q))], 1) if timed else None
    return {"days": days, "requests": len(actions), "turns": len(turns), "failed": failed, "complaints": complaints,
            "clarify": clarify, "approvals": approvals, "lies": lies, "lie_examples": lie_examples, "tails": tails,
            "families": daily, "hangs": hangs, "timed": len(timed), "p50": pct(0.5),
            "p90": pct(0.9), "waited_points": round(waited, 1),
            "B100": round(100 * burden / len(actions), 1) if actions else None,
            "worst_tools": [(name, c["COMPLETED"], sum(c.values()), dict(c)) for name, c in worst],
            "tiers": tiers.most_common(6)}


def markdown(s):
    lines = [f"### Scoreboard: last {s['days']} days ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"**B100 = {s['B100']}** over {s['requests']} requests ({s['turns']} turns). 20x target: B100 / 20.", "",
             "| Burden | Count |", "|---|---|",
             f"| Failed or given up (x5) | {s['failed']} |", f"| Complaints next turn (x3) | {s['complaints']} |",
             f"| Promises with no action, voice (x5, estimate) | {s['lies']} |",
             f"| Clarify questions (x2) | {s['clarify']} |", f"| Approvals asked (x2) | {s['approvals']} |",
             f"| Waiting beyond 5 s (points) | {s['waited_points']} ({s['timed']} timed turns, p50 {s['p50']} s, "
             f"p90 {s['p90']} s) |", f"| Hangs (x20) | {len(s['hangs'])} |",
             f"| Chit-chat question tails (not weighted; target 0) | {s['tails']} |", "",
             "| Worst tools | Completed / total | States |", "|---|---|---|"]
    lines += [f"| `{name}` | {ok}/{total} | {states} |" for name, ok, total, states in s["worst_tools"]]
    lines += ["", "Tiers: " + ", ".join(f"{name} {n}" for name, n in s["tiers"])]
    done = sum(ok for _, ok, _, _ in s["families"])
    lines += ["", f"### The Daily 30: {done}/{s['requests']} requests finished "
              f"({round(100 * done / s['requests']) if s['requests'] else 0}%; target 99%)", "",
              "| Family | Finished / asked | Outcomes |", "|---|---|---|"]
    lines += [f"| `{name}` | {ok}/{total} | {states} |" for name, ok, total, states in s["families"]]
    if s["lie_examples"]:
        lines += ["", "Promises with no action behind them (first 5):"] + [f"- \"{e}\"" for e in s["lie_examples"]]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--base", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    print(markdown(score(Path(args.base), args.days)))


if __name__ == "__main__":
    main()
