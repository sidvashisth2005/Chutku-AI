"""Chat-history search (Phase 3b H4): incremental FTS5 index of conversations.jsonl, Hindi script found in Roman
letters and back, typed search operators are plain words, hidden turns and day limits respected, instant phrases."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from chutku import history_index
from chutku.quick_intents import QUICK_ANSWERS, quick_proposal


def line(said, reply="ok", age=60, **extra):
    return json.dumps({"at": time.time() - age, "origin": "voice", "said": said, "reply": reply} | extra,
                      ensure_ascii=False) + "\n"


class HistoryIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / "data").mkdir()
        self.log = self.base / "data" / "conversations.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, *lines, mode="w"):
        with self.log.open(mode, encoding="utf-8") as stream:
            stream.write("".join(lines))

    def said(self, query, **kwargs):
        return [m["said"] for m in history_index.search(self.base, query, **kwargs)["matches"]]

    def test_incremental_sync_and_partial_lines(self):
        self.write(line("DBMS viva kab hai"), line("open spotify"))
        self.assertEqual(history_index.sync(self.base), 2)
        self.assertEqual(history_index.sync(self.base), 0)               # nothing new
        self.write(line("DBMS notes banao"), '{"at": 1, "said": "half a li', mode="a")
        self.assertEqual(history_index.sync(self.base), 1)               # the unfinished line waits
        self.assertEqual(sorted(self.said("dbms")), ["DBMS notes banao", "DBMS viva kab hai"])

    def test_rewritten_log_is_reindexed(self):
        self.write(line("first topic alpha"), line("second topic beta"))
        history_index.sync(self.base)
        self.write(line("only gamma now"))                               # shorter file: rotated
        self.assertEqual(self.said("alpha"), [])
        self.assertEqual(self.said("gamma"), ["only gamma now"])

    def test_hindi_script_and_roman_find_each_other(self):
        self.write(line("मम्मी को फोन करना है"), line("mammi ka birthday kab hai"))
        self.assertEqual(len(self.said("mammi")), 2)
        self.assertEqual(len(self.said("मम्मी")), 2)

    def test_typed_operators_are_plain_words(self):
        self.write(line("near the station"), line("or else"))
        for query in ('"a" OR *', "NEAR(x y)", "x* AND", "{said} : y", "'; DROP TABLE turns; --"):
            history_index.search(self.base, query)                       # no FTS syntax error
        self.assertEqual(self.said("NEAR"), ["near the station"])

    def test_hidden_turns_and_day_limit(self):
        self.write(line("secret topic zeta", hidden=True), line("old topic eta", age=10 * 86400),
                   line("new topic eta"))
        self.assertEqual(self.said("zeta"), [])
        self.assertEqual(sorted(self.said("eta")), ["new topic eta", "old topic eta"])
        self.assertEqual(self.said("eta", days=7), ["new topic eta"])

    def test_all_words_first_then_any(self):
        self.write(line("gulabi top dekha"), line("gulabi phool"), line("top 10 songs"))
        self.assertEqual(self.said("gulabi top"), ["gulabi top dekha"])
        self.assertEqual(len(self.said("gulabi neela")), 2)               # no turn has both: any word


class HistoryPhraseTests(unittest.TestCase):
    def test_topic_questions_search_history(self):
        cases = {"what did i say about gulabi top": {"query": "gulabi top"},
                 "pichhle hafte DBMS ke baare mein kya baat hui": {"query": "DBMS", "days": 7},
                 "kal mammi ke baare mein kya baat hui thi": {"query": "mammi", "days": 2},
                 "मम्मी के बारे में क्या बात हुई": {"query": "mammi"},
                 "gulabi top wali baat dhoondo": {"query": "gulabi top"},
                 "search my chats for night report": {"query": "night report"}}
        for text, arguments in cases.items():
            step = quick_proposal(text)["next_steps"][0]
            self.assertEqual((step["tool"], step["arguments"]), ("history.search", arguments), text)

    def test_day_summaries_keep_their_meaning(self):
        for text in ("what did we talk about yesterday", "kal humne kya baat ki"):
            proposal = quick_proposal(text)
            self.assertFalse(proposal and proposal.get("next_steps"), text)   # answered directly, no search

    def test_answer_text(self):
        said = QUICK_ANSWERS["history.search"]({"terms": ["gulabi"], "matches": [
            {"date": "Wed 07 Oct 2026, 08:10 AM", "said": "new gulabi top", "reply": "nice"}]})
        self.assertIn("Wed 07 Oct 2026", said)
        self.assertIn("new gulabi top", said)
        self.assertIn("nothing", QUICK_ANSWERS["history.search"]({"terms": ["zz"], "matches": []}))

    def test_tool_is_read_only_tainting_and_private(self):
        from chutku.agent_loop import PRIVATE_TOOLS, TAINTING_TOOLS
        from chutku.tools.builtin import register_builtin_tools
        from chutku.tools.registry import ToolRegistry
        registry = ToolRegistry()
        register_builtin_tools(registry)
        self.assertEqual(int(registry.get("history.search").base_risk), 0)
        self.assertIn("history.search", TAINTING_TOOLS)   # old replies can quote web pages
        self.assertIn("history.search", PRIVATE_TOOLS)


if __name__ == "__main__":
    unittest.main()
