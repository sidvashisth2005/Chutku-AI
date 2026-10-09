"""WhatsApp atlas and the unread count (App Mastery A5). A fake driver stands in for the screen."""
import unittest
from unittest.mock import patch

from chutku.apps import atlas as atlas_module, extras
from chutku.quick_intents import QUICK_ANSWERS, quick_proposal
from chutku.tools.registry import ToolRegistry


class FakeDriver:
    def __init__(self, lines, window=5):
        self.lines, self.window, self.calls = lines, window, []

    def find_window(self, window):
        return self.window

    def focus(self, hwnd):
        self.calls.append("focus")

    def window_rect(self, hwnd):
        return (0, 0, 1000, 1000)

    def ocr(self, rect):
        self.calls.append(("ocr", rect))
        return [{"text": t, "rect": (0, 0, 1, 1)} for t in self.lines]


def steps(goal):
    proposal = quick_proposal(goal, apps=[])
    return [(s["tool"], s["arguments"]) for s in proposal["next_steps"]] if proposal else None


class UnreadTests(unittest.TestCase):
    def test_chip_parsing(self):
        line = lambda t: {"text": t}
        self.assertEqual(extras.unread_from([line("All"), line("Unread 26"), line("Favourites")]), 26)
        self.assertEqual(extras.unread_from([line("Unread")]), 0)
        self.assertIsNone(extras.unread_from([line("Unread messages from Ub")]))   # chat text, not the chip
        self.assertIsNone(extras.unread_from([line("Edit profile")]))

    def run_tool(self, driver):
        with patch.object(extras, "DRIVER", driver), patch("time.sleep"):
            return extras._unread({}, None)

    def test_tool_reads_only_the_chip_area_and_clicks_nothing(self):
        driver = FakeDriver(["Chats", "All", "Unread 3", "Favourites"])
        result = self.run_tool(driver)
        self.assertEqual(result.output, {"app": "whatsapp", "unread_chats": 3})
        self.assertEqual(driver.calls, ["focus", ("ocr", (0, 100, 350, 300))])
        self.assertEqual(QUICK_ANSWERS["message.unread_count"](result.output), "WhatsApp pe 3 chats unread hain.")
        self.assertIn("koi unread", QUICK_ANSWERS["message.unread_count"]({"unread_chats": 0}))

    def test_fails_closed_when_the_list_is_covered_or_whatsapp_is_closed(self):
        result = self.run_tool(FakeDriver(["Edit profile", "Name"]))
        self.assertEqual(str(result.verification.name), "FAIL")
        self.assertIn("did not click", result.output["error"])
        result = self.run_tool(FakeDriver([], window=None))
        self.assertIn("not open", result.output["error"])

    def test_phrases(self):
        for goal in ("whatsapp pe kitne unread messages hain", "how many unread chats on whatsapp",
                     "kitne naye message aaye hain"):
            self.assertEqual(steps(goal), [("message.unread_count", {})], goal)
        self.assertNotEqual(steps("unread messages padho"), [("message.unread_count", {})])

    def test_registered_read_only(self):
        from chutku.apps.tools import register_app_tools
        registry = ToolRegistry()
        register_app_tools(registry)
        tool = registry.get("message.unread_count")
        self.assertEqual(int(tool.base_risk), 0)
        with self.assertRaises(ValueError):
            tool.validate_arguments({"to": "Ub"})


class AtlasTests(unittest.TestCase):
    def test_whatsapp_atlas_never_opens_a_chat_or_sends(self):
        atlases, errors = atlas_module.load_all()
        self.assertEqual(errors, {})
        wa = atlases["whatsapp"]
        self.assertTrue(all(a["risk"] == "safe" for a in wa["actions"]))
        keys = [s.get("keys") for a in wa["actions"] for s in a["steps"] if "keys" in s]
        self.assertNotIn("enter", keys)
        self.assertFalse([k for k in keys if "ctrl+alt+shift" in k])   # mute/unread/archive/pin shortcuts change chats
        self.assertFalse([s for a in wa["actions"] for s in a["steps"] if "type" in s])

    def test_phrases_route_when_verified(self):
        verified = {"whatsapp": {"show_unread", "new_chat", "open"}}
        with patch("chutku.apps.lab.verified_actions", return_value=verified):
            self.assertEqual(steps("whatsapp unread dikhao"), [("app.whatsapp.show_unread", {})])
            self.assertEqual(steps("whatsapp new chat"), [("app.whatsapp.new_chat", {})])
            self.assertEqual(steps("open whatsapp")[0][0], "apps.launch")   # route: false


if __name__ == "__main__":
    unittest.main()
