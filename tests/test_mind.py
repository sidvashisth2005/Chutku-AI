import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import mind
from chutku.app import create_runtime
from chutku.mind_intent import parse_mind


class MindTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = patch.object(mind, "PROJECT_ROOT", Path(self.temp.name))
        self.root.start()
        self.mind = mind.default()

    def tearDown(self):
        self.root.stop()
        self.temp.cleanup()


class MindStoreTests(MindTestCase):
    def test_nicknames_relations_and_hinglish_find_the_same_person(self):
        self.mind.remember_person("AK", aliases=["gf"])
        self.mind.remember_person("Mummy", aliases=["mammi"], phone="+91 98765 43210")
        self.mind.remember_person("Sharma Sir", aliases=["DL wale sir"])
        for said, name in (("gf", "AK"), ("my GF", "AK"), ("meri gf", "AK"), ("girlfriend", "AK"), ("AK", "AK"),
                           ("mammi", "Mummy"), ("mom", "Mummy"), ("mother", "Mummy"), ("mammi ko", "Mummy"),
                           ("DL waale sir", "Sharma Sir"), ("mere DL vale sir", "Sharma Sir")):
            self.assertEqual(self.mind.find_person(said)["name"], name, said)

    def test_never_guesses_unknown_ambiguous_or_lookalike_people(self):
        self.mind.remember_person("Mummy", aliases=["mammi"])
        self.mind.remember_person("Rohit", relation="brother")
        self.mind.remember_person("Aman", relation="brother")
        self.assertIsNone(self.mind.find_person("mama"))         # mama is an uncle, not mom
        self.assertIsNone(self.mind.find_person("bhai"))         # two brothers: ambiguous
        self.assertIsNone(self.mind.find_person("Rahul"))
        self.assertIsNone(self.mind.find_person("Mumm"))         # no fuzzy matching
        self.assertIsNone(self.mind.find_person(""))

    def test_newest_nickname_wins_and_data_is_merged_not_lost(self):
        self.mind.remember_person("AK", aliases=["gf"], note="likes coffee")
        self.mind.remember_person("Riya", aliases=["gf"])
        self.assertEqual(self.mind.find_person("gf")["name"], "Riya")
        self.mind.remember_person("ak", phone="+919999999999")
        people = self.mind.load()["people"]
        self.assertEqual(len(people), 2)
        ak = next(p for p in people if p["name"] == "AK")
        self.assertEqual((ak["phone"], ak["notes"]), ("+919999999999", ["likes coffee"]))

    def test_facts_lists_done_and_forget(self):
        self.mind.set_fact("Home", "Pune")
        item = self.mind.add("assignment", "DBMS report")
        self.assertEqual((item["list"], item["id"]), ("assignments", 1))
        self.mind.mark_done("assignments", 1)
        data = self.mind.load()
        self.assertEqual(data["facts"], {"home": "Pune"})
        self.assertTrue(data["lists"]["assignments"][0]["done"])
        self.mind.forget("item", "assignments:1")
        self.assertEqual(self.mind.load()["lists"]["assignments"], [])
        with self.assertRaises(ValueError):
            self.mind.add("groceries", "milk")
        with self.assertRaises(ValueError):
            self.mind.forget("person", "nobody")

    def test_store_is_plain_local_json_and_survives_a_corrupt_file(self):
        self.mind.remember_person("AK", aliases=["gf"])
        stored = json.loads((Path(self.temp.name) / "data" / "mind.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["people"][0]["name"], "AK")
        (Path(self.temp.name) / "data" / "mind.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(self.mind.load()["people"], [])


class MindPhraseTests(MindTestCase):
    def tool(self, text):
        found = parse_mind(text)
        return None if found is None else (found[0], found[1])

    def test_teaching_phrases(self):
        self.assertEqual(self.tool("AK is my gf"), ("mind.person", {"name": "AK", "aliases": ["gf"]}))
        self.assertEqual(self.tool("AK meri gf hai"), ("mind.person", {"name": "AK", "aliases": ["gf"]}))
        self.assertEqual(self.tool("remember Sharma Sir is my DL wale sir"),
                         ("mind.person", {"name": "Sharma Sir", "aliases": ["DL wale sir"]}))
        self.assertEqual(self.tool("mammi ka number +91 98765 43210 hai")[1]["phone"], "+919876543210")
        self.assertEqual(self.tool("mera ghar Pune mein hai"), ("mind.fact", {"key": "home", "value": "Pune"}))
        self.assertEqual(self.tool("add assignment: DBMS report by Friday"),
                         ("mind.add", {"list": "assignments", "text": "DBMS report by Friday"}))
        self.assertEqual(self.tool("assignment 2 done"), ("mind.done", {"list": "assignments", "id": 2}))
        self.assertEqual(self.tool("mere assignments dikhao"), ("mind.show", {"part": "assignments"}))
        self.assertEqual(self.tool("what do you know about me"), ("mind.show", {"part": "all"}))
        self.assertEqual(self.tool("who is my gf"), ("mind.who", {"name": "gf"}))

    def test_facts_and_general_questions_are_not_people(self):
        self.assertIsNone(self.tool("remember my city is Pune"))     # stays memory.remember
        self.assertIsNone(self.tool("who is the president of India"))
        self.assertIsNone(self.tool("what is my name"))

    def test_messages_without_an_app_only_for_people_already_known(self):
        self.assertIsNone(self.tool("send hi to my gf"))              # nobody saved yet: never a guess
        self.mind.remember_person("AK", aliases=["gf"])
        self.assertEqual(self.tool("send hi to my gf"), ("message.send", {"app": "whatsapp", "to": "gf", "text": "hi"}))
        self.assertEqual(self.tool("gf ko good night bhejo"),
                         ("message.send", {"app": "whatsapp", "to": "gf", "text": "good night"}))
        self.assertIsNone(self.tool("send hi to Rahul"))
        self.assertIsNone(self.tool("send a message to gf"))          # no actual text
        self.assertIsNone(self.tool("send hi to gf on whatsapp"))     # app named: message_intent handles it

    def test_recipient_maps_nickname_to_chat_or_number(self):
        from chutku.tools.apps_extra import recipient, resolve_contact
        self.mind.remember_person("AK", aliases=["gf"])
        self.mind.remember_person("Mummy", aliases=["mammi"], phone="+919876543210")
        self.assertEqual(recipient("my gf"), ("", "AK", "AK"))
        self.assertEqual(resolve_contact("mammi", None), ("+919876543210", "Mummy"))
        self.assertIsNone(recipient("Rahul"))
        with self.assertRaises(ValueError):
            resolve_contact("gf", None)   # AK has no number: the named-chat path is used instead


class MindToolTests(MindTestCase):
    def test_tools_store_read_and_forgetting_asks_first(self):
        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            self.assertEqual(runtime.run("mind.person", {"name": "AK", "aliases": ["gf"]})["state"], "COMPLETED")
            who = runtime.run("mind.who", {"name": "gf"})
            self.assertEqual(who["output"]["person"]["name"], "AK")
            self.assertEqual(runtime.run("mind.add", {"list": "skills", "text": "python"})["state"], "COMPLETED")
            self.assertEqual(runtime.run("mind.show", {"part": "skills"})["output"]["lists"]["skills"][0]["text"],
                             "python")
            forget = runtime.run("mind.forget", {"kind": "person", "key": "gf"})
            self.assertEqual(forget["state"], "WAITING_CONFIRMATION")     # a deletion: always asks
            self.assertIsNotNone(self.mind.find_person("gf"))
            self.assertEqual(runtime.run("mind.person", {"name": "x", "phone": "call me"})["state"], "FAILED")


class MindSessionTests(MindTestCase):
    def test_teach_then_ask_runs_instantly_without_the_model(self):
        from chutku.agent_loop import AgentSession, RuntimeRouter, default_context
        from chutku.quick_intents import QuickPlanner

        class NoModel:
            name = "local"

            def propose(self, *args, **kwargs):
                raise AssertionError("the model planner must not be needed")

            def answer(self, *args, **kwargs):
                raise AssertionError("the model must not reword an instant answer")

        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            router = RuntimeRouter(runtime)
            try:
                for goal, expected in (("AK is my gf", "gf = AK"), ("add assignment: DBMS report by Friday", "Added"),
                                       ("who is my gf", "gf is AK"), ("show my assignments", "1. DBMS report by Friday")):
                    session = AgentSession(goal, mode="auto_safe", context=default_context(router))
                    session.quick = QuickPlanner()
                    snapshot = session.advance(router, NoModel())
                    self.assertEqual(snapshot["status"], "done", (goal, snapshot))
                    self.assertIn(expected, snapshot["reply"], goal)
            finally:
                router.close()


if __name__ == "__main__":
    unittest.main()
