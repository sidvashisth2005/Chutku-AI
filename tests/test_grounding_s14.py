"""State-grounded decoding and tool confidence (master plan S14)."""
import math
import unittest

from chutku.agent_loop import agent_schema, goal_phrases, ground_schemas
from chutku.brain_service import tool_confidence
from chutku.profiles import QWEN

SCHEMAS = {
    "apps.launch": {"type": "object", "properties": {"name": {"type": "string", "maxLength": 120}}},
    "message.send": {"type": "object", "properties": {"to": {"type": "string"}, "text": {"type": "string"}}},
    "system.get_time": {"type": "object", "properties": {}},
}
FOUND = {"apps": ["Calculator", "Spotify"], "contacts": ["AK", "mammi"]}


class GroundingTests(unittest.TestCase):
    def test_names_must_exist_or_be_said_by_the_owner(self):
        grounded = ground_schemas(SCHEMAS, FOUND, "open photoshop")
        apps = grounded["apps.launch"]["properties"]["name"]["enum"]
        self.assertIn("Spotify", apps)
        self.assertIn("photoshop", apps)
        self.assertIn("Photoshop", apps)          # the owner's word, capitalised
        self.assertNotIn("Photoshop CC", apps)    # nothing invented
        self.assertEqual(set(grounded["message.send"]["properties"]["to"]["enum"]) & {"AK", "mammi"}, {"AK", "mammi"})
        self.assertNotIn("enum", grounded["message.send"]["properties"]["text"])   # message text stays free

    def test_the_tools_own_schemas_are_not_changed(self):
        ground_schemas(SCHEMAS, FOUND, "open spotify")
        self.assertNotIn("enum", SCHEMAS["apps.launch"]["properties"]["name"])

    def test_nothing_known_means_no_restriction(self):
        grounded = ground_schemas(SCHEMAS, {"apps": [], "contacts": []}, "open spotify")
        self.assertNotIn("enum", grounded["apps.launch"]["properties"]["name"])

    def test_the_grammar_carries_the_enum(self):
        grammar = agent_schema(ground_schemas(SCHEMAS, FOUND, "open spotify"), QWEN)
        forms = grammar["properties"]["next_steps"]["items"]["anyOf"]
        launch = next(f for f in forms if f["properties"]["tool"]["enum"] == ["apps.launch"])
        self.assertIn("Calculator", launch["properties"]["arguments"]["properties"]["name"]["enum"])

    def test_goal_phrases(self):
        self.assertIn("pita shri", goal_phrases("send hi to pita shri"))


class ConfidenceTests(unittest.TestCase):
    def test_probability_of_the_first_tool_token(self):
        tokens = [{"token": '{"status":"continue","next_steps":[{"tool":"', "logprob": 0.0},
                  {"token": "apps", "logprob": math.log(0.6)}, {"token": ".launch", "logprob": 0.0}]
        self.assertEqual(tool_confidence(tokens), 0.6)
        self.assertIsNone(tool_confidence([]))
        self.assertIsNone(tool_confidence([{"token": '{"status":"done"}', "logprob": 0.0}]))


if __name__ == "__main__":
    unittest.main()
