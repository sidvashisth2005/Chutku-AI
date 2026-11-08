"""H16: Telegram remote control, tested with a fake Bot API (nothing is sent anywhere)."""
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku.agent_loop import AgentSession, AgentSessionStore
from chutku.gateway import telegram

OWNER, STRANGER = 111, 999
TOKEN = "123456789:" + "A" * 35


class FakeApi:
    def __init__(self):
        self.sent, self.updates = [], []

    def __call__(self, method, params, timeout):
        if method == "getUpdates":
            updates, self.updates = self.updates, []
            return updates
        self.sent.append((method, params))
        return {"ok": True}

    def texts(self):
        return [p["text"] for m, p in self.sent if m == "sendMessage"]


class FakeCore:
    """The parts of DashboardServer the gateway uses."""

    def __init__(self, base, status="waiting_confirmation", tool="filesystem.recycle", risk=2):
        self.base = base
        self.agent_sessions = AgentSessionStore()
        self.status, self.tool, self.risk = status, tool, risk
        self.decisions, self.goals = [], []

        class Prefs:
            def load(self):
                return {"handsfree_mode": "owner"}
        self.preferences = Prefs()

    def _known_names(self):
        return []

    def begin_session(self, goal, mode, origin):
        self.goals.append((goal, origin))
        session = self.agent_sessions.add(AgentSession(goal, mode=mode, origin=origin))
        with session.lock:
            if self.status == "waiting_confirmation":
                step = {"tool": self.tool, "arguments": {"path": "C:\\Users\\me\\old.txt"}, "purpose": "p"}
                session.pending = {"step": step, "approval": {"token": "t", "tool": self.tool,
                                                              "arguments": step["arguments"], "risk": self.risk,
                                                              "reason": "asks first"}}
                session.status = "waiting_confirmation"
            else:
                session._finish("done", "Volume 30 kar diya.")
        return session

    def confirm_session(self, session_id, approve):
        self.decisions.append((session_id, approve))
        session = self.agent_sessions.get(session_id)
        with session.lock:
            session._finish("done" if approve else "cancelled", "ok")
        return session.snapshot()


def message(chat, text):
    return {"update_id": 1, "message": {"chat": {"id": chat}, "text": text}}


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / "data").mkdir()
        self.api = FakeApi()
        self.now = [1_000_000.0]
        self.core = FakeCore(self.base)
        self.gateway = telegram.Gateway(self.base, self.core, transport=self.api, clock=lambda: self.now[0],
                                        laptop_only=lambda approval: approval.get("risk", 0) >= 4
                                        or approval.get("tool") == "code.run_python")

    def pair(self):
        code = self.gateway.new_code()
        self.assertEqual(self.gateway.handle(message(OWNER, f"/pair {code}")), "paired")

    def test_an_unpaired_chat_is_ignored_without_a_reply(self):
        self.assertEqual(self.gateway.handle(message(STRANGER, "volume 30")), "ignored")
        self.pair()
        self.api.sent.clear()
        self.assertEqual(self.gateway.handle(message(STRANGER, "volume 30")), "ignored")
        self.assertEqual(self.api.sent, [])
        self.assertEqual(self.core.goals, [])

    def test_link_gives_the_phone_remote_link_to_the_owner_only(self):
        # owner 2026-11-07: the live link comes on Telegram, and "/link" brings it back if it is lost
        from chutku.remote.auth import RemoteStore
        RemoteStore(self.base).configure(host="laptop.tail1.ts.net", login="me@example.com", enabled=True)
        self.assertEqual(self.gateway.handle(message(STRANGER, "/link")), "ignored")
        self.assertEqual(self.api.texts(), [])
        self.pair()
        self.api.sent.clear()
        self.assertEqual(self.gateway.handle(message(OWNER, "/link")), "link")
        self.assertIn("https://laptop.tail1.ts.net/", self.api.texts()[-1])
        self.assertEqual(self.core.goals, [])                                      # not a task for the planner
        RemoteStore(self.base).configure(enabled=False)
        self.gateway.handle(message(OWNER, "link"))
        self.assertIn("phone connect karo", self.api.texts()[-1])

    def test_wrong_codes_lock_pairing(self):
        self.gateway.new_code()
        for _ in range(telegram.MAX_WRONG):
            self.assertEqual(self.gateway.handle(message(STRANGER, "/pair WRONGWRO")), "ignored")
        with self.assertRaises(ValueError):
            self.gateway.new_code()
        self.now[0] += telegram.LOCKOUT + 1
        self.gateway.new_code()

    def test_an_expired_code_is_refused(self):
        code = self.gateway.new_code()
        self.now[0] += telegram.CODE_TTL + 1
        self.assertEqual(self.gateway.handle(message(OWNER, f"/pair {code}")), "ignored")
        self.assertIsNone(telegram.paired(self.base))

    def test_more_than_three_pending_codes_is_refused(self):
        for _ in range(telegram.MAX_PENDING):
            self.gateway.new_code()
        with self.assertRaises(ValueError):
            self.gateway.new_code()

    def test_a_request_and_its_result(self):
        self.core.status = "done"
        self.pair()
        self.assertEqual(self.gateway.handle(message(OWNER, "volume 30")), "request")
        self.assertEqual(self.core.goals, [("volume 30", "phone")])
        self.assertIn("Volume 30 kar diya.", self.api.texts())

    def test_approval_buttons_single_use_and_bound_to_the_chat(self):
        self.pair()
        self.gateway.handle(message(OWNER, "old.txt recycle karo"))
        card = [p for m, p in self.api.sent if m == "sendMessage" and "reply_markup" in p][-1]
        approve = card["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        other_chat = {"callback_query": {"id": "q", "data": approve, "message": {"chat": {"id": STRANGER}}}}
        self.assertEqual(self.gateway.handle(other_chat), "ignored")
        mine = {"callback_query": {"id": "q", "data": approve, "message": {"chat": {"id": OWNER}}}}
        self.assertEqual(self.gateway.handle(mine), "approved")
        self.assertEqual(len(self.core.decisions), 1)
        self.assertEqual(self.gateway.handle(mine), "stale")             # replayed nonce
        self.assertEqual(len(self.core.decisions), 1)

    def test_an_expired_nonce_is_refused(self):
        self.pair()
        self.gateway.handle(message(OWNER, "old.txt recycle karo"))
        card = [p for m, p in self.api.sent if "reply_markup" in p][-1]
        self.now[0] += telegram.NONCE_TTL + 1
        query = {"callback_query": {"id": "q", "data": card["reply_markup"]["inline_keyboard"][0][0]["callback_data"],
                                    "message": {"chat": {"id": OWNER}}}}
        self.assertEqual(self.gateway.handle(query), "stale")
        self.assertEqual(self.core.decisions, [])

    def test_r4_and_code_never_run_from_telegram(self):
        self.pair()
        for tool, risk in (("power.shutdown", 4), ("code.run_python", 3)):
            self.core.tool, self.core.risk = tool, risk
            self.api.sent.clear()
            self.gateway.handle(message(OWNER, f"run {tool}"))
            self.assertFalse(any("reply_markup" in p for m, p in self.api.sent), tool)   # no buttons at all
            self.assertTrue(any("PC pe approve" in t for t in self.api.texts()), tool)
        self.assertEqual(self.core.decisions, [])

    def test_the_real_laptop_only_rule_covers_telegram_settings(self):
        from chutku.remote.server import laptop_only
        self.assertTrue(laptop_only({"tool": "telegram.handoff", "risk": 1}, lambda tool: False))
        self.assertTrue(laptop_only({"tool": "files.open", "risk": 1}, lambda tool: True))   # runs code / unknown
        self.assertFalse(laptop_only({"tool": "filesystem.move", "risk": 2}, lambda tool: False))

    def test_pause_answers_paused(self):
        from chutku.core.action_control import ActionControl
        self.pair()
        ActionControl(self.base).pause("owner", "asked")
        self.assertEqual(self.gateway.handle(message(OWNER, "volume 30")), "paused")
        self.assertEqual(self.core.goals, [])

    def test_rate_limit(self):
        self.core.status = "done"
        self.pair()
        for _ in range(telegram.RATE_PER_HOUR):
            self.gateway.handle(message(OWNER, "volume 30"))
        self.assertEqual(self.gateway.handle(message(OWNER, "volume 30")), "rate_limited")

    def test_voice_notes_wait_while_the_voice_lock_is_on(self):
        from chutku.core.preferences import Preferences
        self.pair()
        Preferences(self.base).update({"voice_lock": True})
        update = {"update_id": 2, "message": {"chat": {"id": OWNER}, "voice": {"file_id": "f", "file_size": 10}}}
        self.assertEqual(self.gateway.handle(update), "voice_refused")
        self.assertEqual(self.core.goals, [])

    def test_handoff_and_delivery(self):
        self.pair()
        self.assertFalse(telegram.deliver(self.base, "research done"))   # no active gateway
        telegram._ACTIVE["gateway"] = self.gateway
        self.addCleanup(telegram._ACTIVE.update, {"gateway": None})
        self.assertFalse(telegram.deliver(self.base, "research done"))   # paired but not handed off
        self.assertEqual(self.gateway.handle(message(OWNER, "main bahar ja raha hoon, phone pe batana")), "handoff")
        self.assertTrue(telegram.deliver(self.base, "research done"))
        self.assertEqual(self.gateway.handle(message(OWNER, "main wapas aa gaya")), "handoff_end")
        self.assertFalse(self.gateway.handed_off())

    def test_the_token_is_never_logged_or_stored(self):
        records = []

        class Keep(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())
        handler = Keep()
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)

        def failing(method, params, timeout):
            raise telegram.TelegramError("Telegram answered HTTP 401 to getUpdates.")
        gateway = telegram.Gateway(self.base, self.core, transport=failing)
        with self.assertRaises(telegram.TelegramError) as raised:
            gateway.poll_once()
        self.assertNotIn(TOKEN, str(raised.exception))
        self.pair()
        self.assertNotIn(TOKEN, json.dumps(telegram.load(self.base)))
        self.assertFalse(any(TOKEN in line for line in records))

    def test_back_home_without_telegram_is_just_a_greeting(self):
        from tests.agent_fakes import real_registry
        registry = real_registry()
        telegram.register_telegram_tools(registry, self.base)
        back = registry.get("telegram.handoff").execute({"on": False}, None)
        self.assertEqual((back.verification, back.output["summary"]), ("PASS", "Welcome back!"))
        away = registry.get("telegram.handoff").execute({"on": True}, None)
        self.assertEqual(away.verification, "FAIL")   # nothing is paired: say so, do not pretend

    def test_token_format(self):
        with self.assertRaises(ValueError):
            telegram.store_token("not-a-token")

    def test_the_tap_to_pair_link_pairs_and_wrong_start_codes_count(self):
        # 2026-11-08: the dashboard's QR opens t.me/<bot>?start=CODE, which sends "/start CODE"
        self.assertEqual(self.gateway.handle(message(STRANGER, "/start")), "ignored")   # no code: not a wrong try
        self.assertEqual(telegram.load(self.base).get("wrong", []), [])
        self.gateway.new_code()
        for _ in range(telegram.MAX_WRONG):
            self.assertEqual(self.gateway.handle(message(STRANGER, "/start WRONGWRO")), "ignored")
        self.assertIsNone(telegram.paired(self.base))
        with self.assertRaises(ValueError):                                         # locked, as with /pair
            self.gateway.new_code()
        self.now[0] += telegram.LOCKOUT + 1
        code = self.gateway.new_code()
        self.assertEqual(self.gateway.handle(message(OWNER, f"/start {code}")), "paired")
        self.assertEqual(telegram.paired(self.base), OWNER)
        self.assertEqual(self.gateway.handle(message(OWNER, f"/start {code}")), "link")   # again: not a task
        self.assertEqual(self.core.goals, [])

    def test_a_token_is_stored_only_when_telegram_knows_it(self):
        from unittest.mock import patch
        calls = []

        def knows(method, params, timeout):
            calls.append(method)
            return {"username": "asha_chutku_bot"}

        def refuses(method, params, timeout):
            raise telegram.TelegramError("Telegram answered HTTP 401 to getMe.")
        with patch.object(telegram, "store_token") as store:
            with self.assertRaises(ValueError):
                telegram.connect_token(self.base, "not-a-token", transport=knows)
            self.assertEqual(calls, [])                                             # never sent anywhere
            with self.assertRaises(ValueError) as refused:
                telegram.connect_token(self.base, TOKEN, transport=refuses)
            self.assertNotIn(TOKEN, str(refused.exception))
            store.assert_not_called()
            self.assertEqual(telegram.connect_token(self.base, " " + TOKEN + "\n", transport=knows), "asha_chutku_bot")
            store.assert_called_once_with(TOKEN)
        self.assertEqual(telegram.load(self.base)["bot"], "asha_chutku_bot")
        self.assertNotIn(TOKEN, telegram.state_path(self.base).read_text())

    def test_poll_once_saves_the_offset(self):
        self.api.updates = [{"update_id": 41, "message": {"chat": {"id": STRANGER}, "text": "hi"}}]
        self.assertEqual(self.gateway.poll_once(), ["ignored"])
        self.assertEqual(telegram.load(self.base)["offset"], 42)

    def test_the_start_up_link_is_tried_again_until_telegram_answers(self):
        # owner 2026-11-08: after a restart the hotspot's DNS was broken for minutes and the one try was lost
        import threading
        now, sent, tries = {"t": 0.0}, [], {"n": 0}

        class Closing:
            def wait(self, seconds):
                now["t"] += seconds
                return False

        def send(text):
            tries["n"] += 1
            if tries["n"] < 4:
                raise OSError("Telegram is not reachable")
            sent.append(text)
        self.assertTrue(telegram._until_sent(send, lambda: "link", Closing(), clock=lambda: now["t"]))
        self.assertEqual((sent, tries["n"], now["t"]), (["link"], 4, 60.0))   # 3 failures, 20 s apart
        never = {"n": 0}

        def down(text):
            never["n"] += 1
            raise OSError("down")
        now["t"] = 0.0
        self.assertFalse(telegram._until_sent(down, lambda: "link", Closing(), clock=lambda: now["t"]))
        self.assertLessEqual(now["t"], 900.0)                                    # gives up after 15 minutes
        stop = threading.Event(); stop.set()
        self.assertFalse(telegram._until_sent(down, lambda: "link", stop))       # Chutku closing: stops at once


if __name__ == "__main__":
    unittest.main()
