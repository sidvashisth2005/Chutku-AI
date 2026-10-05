from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku.app import create_runtime


WORKFLOW = {"url": "http://127.0.0.1:8080/", "browser": "edge", "steps": [{
    "action": "fill", "locator": {"by": "label", "value": "Name"}, "text": "Ada",
    "expect": {"locator": {"by": "label", "value": "Name"}, "property": "value", "expected": "Ada"}}]}


class BrowserTests(unittest.TestCase):
    def test_inspection_requires_navigation_capability_and_redacts_content_audit(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            args = {"url": "http://127.0.0.1:8080/", "browser": "edge"}
            self.assertEqual(runtime.run("browser.inspect", args)["state"], "DENIED")
            runtime.capability_grants.grant("browser.navigate")
            observed = {"requested_url": args["url"], "final_url": args["url"], "title": "Private",
                        "headings": ["Secret"], "buttons": ["Go"]}
            with patch("chutku.tools.browser._session", return_value=observed):
                self.assertEqual(runtime.run("browser.inspect", args)["state"], "COMPLETED")
            audit = str(runtime.event_log._connection.execute("SELECT payload_json FROM events").fetchall())
            self.assertNotIn("Secret", audit); self.assertNotIn("Private", audit)

    def test_workflow_requires_input_capability_review_and_verified_result(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            self.assertEqual(runtime.run("browser.workflow", WORKFLOW)["state"], "DENIED")
            runtime.capability_grants.grant("browser.input")
            pending = runtime.run("browser.workflow", WORKFLOW)
            self.assertEqual(pending["state"], "WAITING_CONFIRMATION")
            with patch("chutku.tools.browser._session", return_value={"final_url": WORKFLOW["url"], "steps_completed": 1, "verified": True}):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "COMPLETED")

    def test_invalid_urls_locators_and_postconditions_fail_before_browser(self):
        bad = [
            {**WORKFLOW, "url": "file:///C:/secret"},
            {**WORKFLOW, "steps": [{**WORKFLOW["steps"][0], "locator": {"by": "role", "value": "Go"}}]},
            {**WORKFLOW, "steps": [{**WORKFLOW["steps"][0], "expect": {"locator": {"by": "label", "value": "Name"}, "property": "checked", "expected": "yes"}}]},
        ]
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("browser.input")
            with patch("chutku.tools.browser._session") as session:
                for args in bad: self.assertEqual(runtime.run("browser.workflow", args)["state"], "FAILED")
                session.assert_not_called()

    def test_failed_browser_postcondition_never_completes(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("browser.input")
            pending = runtime.run("browser.workflow", WORKFLOW)
            with patch("chutku.tools.browser._session", side_effect=OSError("postcondition failed")):
                self.assertEqual(runtime.approve(pending["approval"]["token"])["state"], "FAILED")


if __name__ == "__main__": unittest.main()
