"""W6: the H9 key pool, the H23 habit-to-automation card and the daily blueprint, and the Board/Automations APIs."""
from datetime import datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku import blueprints, providers


def reply(obj):
    return {"choices": [{"message": {"content": json.dumps(obj)}}]}


class KeyPoolTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_a_quota_on_one_key_moves_to_the_next_key_of_the_same_model(self):
        used = []

        def chat(provider, model, system, user, *, key=None, transport=None, timeout=25):
            used.append((model, key))
            if key == "key-one":
                raise providers.ProviderError("quota", kind="quota", retry_after=30)
            return {"ok": True}, 0.1
        with patch.object(providers, "keys", return_value=[("1", "key-one"), ("2", "key-two")]), \
                patch.object(providers, "chat_json", side_effect=chat):
            parsed, meta = providers.ask("s", "u", base=self.base, rungs=[("groq", "a"), ("groq", "b")])
        self.assertEqual((parsed, meta["model"], meta["key_slot"]), ({"ok": True}, "a", "2"))
        self.assertEqual(used, [("a", "key-one"), ("a", "key-two")])
        cold = providers.cooling(self.base)
        self.assertIn("groq/a#1", cold)                 # only that key cools down, named by its slot
        self.assertNotIn("groq/a", cold)
        self.assertFalse(any("key-one" in name for name in cold))   # never the key's text

    def test_the_model_cools_down_only_when_its_last_key_is_out(self):
        def chat(provider, model, system, user, *, key=None, transport=None, timeout=25):
            if model == "a":
                raise providers.ProviderError("quota", kind="quota", retry_after=30)
            return {"ok": True}, 0.1
        with patch.object(providers, "keys", return_value=[("1", "k1"), ("2", "k2")]), \
                patch.object(providers, "chat_json", side_effect=chat):
            _, meta = providers.ask("s", "u", base=self.base, rungs=[("groq", "a"), ("groq", "b")])
        self.assertEqual(meta["model"], "b")
        self.assertIn("groq/a", providers.cooling(self.base))
        self.assertIn("groq/a#1", providers.cooling(self.base))

    def test_a_cooled_key_is_skipped_next_time(self):
        providers.cool_down("groq/a#1", 60, self.base)
        used = []
        with patch.object(providers, "keys", return_value=[("1", "k1"), ("2", "k2")]), \
                patch.object(providers, "chat_json",
                             side_effect=lambda *a, key=None, **k: (used.append(key), ({"ok": 1}, 0.1))[1]):
            providers.ask("s", "u", base=self.base, rungs=[("groq", "a")])
        self.assertEqual(used, ["k2"])

    def test_keys_come_from_the_numbered_credential_slots(self):
        stored = {"Chutku/Groq#3": "third", "Chutku/Groq#2": "first"}   # #2 repeats the primary: dropped
        with patch.object(providers, "api_key", return_value="first"), \
                patch("chutku.cloud_planner.stored_key", side_effect=lambda target=None: stored.get(target)):
            self.assertEqual(providers.keys("groq"), [("1", "first"), ("3", "third")])

    def test_add_key_takes_the_first_free_slot_and_refuses_a_full_pool(self):
        vault = {"Chutku/Groq": "a", "Chutku/Groq#2": "b"}
        slot = providers.add_key("groq", "c", stored=vault.get, store=lambda key, target: vault.__setitem__(target, key))
        self.assertEqual((slot, vault["Chutku/Groq#3"]), (3, "c"))
        full = {providers.slot_target("Chutku/Groq", n): "x" for n in range(1, providers.POOL_SLOTS + 1)}
        with self.assertRaises(ValueError):
            providers.add_key("groq", "d", stored=full.get, store=lambda *a: None)

    def test_gemini_moves_to_the_next_key_on_429(self):
        from chutku.cloud_planner import GeminiAgentPlanner
        from chutku.gemini import GeminiUnavailable
        planner = GeminiAgentPlanner("g1", keys=["g1", "g2"])
        seen = []

        def call(system, user, schema):
            seen.append(planner.key)
            if planner.key == "g1":
                raise GeminiUnavailable("quota", status=429)
            return {"plan": {"status": "done", "reply": "ok", "declared_plan": [], "next_steps": [], "finish": False},
                    "model": "gemini-x"}
        planner.transport = call
        from agent_fakes import FakeRuntime
        from chutku.agent_loop import AgentSession
        proposal, meta = planner.propose(AgentSession("hello", mode="owner"), FakeRuntime())
        self.assertEqual((seen, proposal["status"]), (["g1", "g2"], "done"))
        planner = GeminiAgentPlanner("g1", keys=["g1"])
        planner.transport = lambda *a: (_ for _ in ()).throw(GeminiUnavailable("quota", status=429))
        with self.assertRaises(OSError):
            planner.propose(AgentSession("hello", mode="owner"), FakeRuntime())


class DailyAndHabitTests(unittest.TestCase):
    def test_daily_phrase_and_build(self):
        from chutku.quick_intents import quick_proposal
        step = quick_proposal("har roz 8:00 baje weather batao")["next_steps"][0]["arguments"]
        self.assertEqual((step["goal"], step["every_minutes"]), ("weather batao", 1440))
        with self.assertRaises(ValueError):
            blueprints.build("daily", {"time": "08:00", "goal": "x"})          # too short
        with self.assertRaises(ValueError):
            blueprints.build("daily", {"goal": "weather batao"})              # time required

    def test_a_habit_becomes_an_automation_card_only_once(self):
        from chutku import scheduled, suggest
        from chutku.mind import Mind
        with TemporaryDirectory() as temp:
            base = Path(temp)
            mind = Mind(base)
            data = mind.load()
            data["habits"] = {"h": {"said": "weather batao", "hour": 8}}
            mind._save(data)
            cards = [c for c in suggest.candidates(base, now=datetime(2026, 11, 7, 15).timestamp(), free_c_gb=100)
                     if c["kind"] == "automation"]
            self.assertEqual(len(cards), 1)
            self.assertEqual(cards[0]["command"], "har roz 8:00 baje weather batao")
            # the next 8:00 from today (a fixed 2026-11-08 08:00 became "in the past" that morning)
            eight = (datetime.now() + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
            scheduled.add(base, "weather batao", eight, every_minutes=1440)
            again = [c for c in suggest.candidates(base, now=datetime(2026, 11, 7, 15).timestamp(), free_c_gb=100)
                     if c["kind"] == "automation"]
            self.assertEqual(again, [])                  # already automated: no card


class TabApiTests(unittest.TestCase):
    def setUp(self):
        from test_setup_page_w5 import Server
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.web = Server(self.temp.name)
        self.addCleanup(self.web.close)

    def test_the_tabs_refuse_a_bad_token(self):
        for method, path, body in (("GET", "/api/automations", None), ("POST", "/api/automations", {"action": "cancel", "id": "x"}),
                                   ("POST", "/api/board", {"action": "done", "id": 1})):
            self.assertEqual(self.web.call(method, path, body, token="nope")[0], 403, path)

    def test_automations_catalog_and_board_buttons(self):
        status, view = self.web.call("GET", "/api/automations")
        self.assertEqual(status, 200)
        self.assertIn("daily", {item["name"] for item in view["catalog"]})
        self.assertEqual(self.web.call("POST", "/api/automations", {"action": "create", "name": "nope"})[0], 400)
        from chutku import board
        mine = board.add(self.temp.name, "DBMS notes banana")
        research = board.add(self.temp.name, "pdf editors", kind="research")
        status, view = self.web.call("POST", "/api/board", {"action": "done", "id": mine["id"]})
        self.assertEqual((status, board.get(self.temp.name, mine["id"])["status"]), (200, "done"))
        board.set_status(self.temp.name, research["id"], "blocked", error="stalled")
        self.web.call("POST", "/api/board", {"action": "again", "id": research["id"]})
        again = board.get(self.temp.name, research["id"])
        self.assertEqual((again["status"], again["attempts"], again["error"]), ("ready", 0, None))
        self.assertEqual(self.web.call("POST", "/api/board", {"action": "again", "id": mine["id"]})[0], 400)
        self.web.call("POST", "/api/board", {"action": "archive", "id": mine["id"]})
        self.assertEqual(len(board.tasks(self.temp.name, include_archived=True)), 2)   # archived, not deleted


if __name__ == "__main__":
    unittest.main()
