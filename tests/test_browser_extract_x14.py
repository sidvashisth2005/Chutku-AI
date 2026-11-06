"""X14 (2026-11-06): tables and lists from a public page, as rows; outside content."""
import unittest
from unittest.mock import patch

from chutku.tools import internet

PAGE = """<html><head><style>td{x}</style><script>var a='<td>evil</td>';</script></head><body>
<ul><li>Home</li><li>About</li></ul>
<table><tr><th>Phone</th><th>Price<br>today</th></tr><tr><td>Alpha 5</td><td>&#8377;12,999</td></tr>
<tr><td>Beta X</td><td> 14,499 </td></tr></table>
<ol><li>Fast charging</li><li>OLED screen</li><li>5G</li></ol></body></html>"""


class ExtractTests(unittest.TestCase):
    def test_tables_and_real_lists_come_out_as_rows(self):
        tables, lists = internet.extract_structured(PAGE)
        self.assertEqual(tables, [[["Phone", "Price today"], ["Alpha 5", "₹12,999"], ["Beta X", "14,499"]]])
        self.assertEqual(lists, [["Fast charging", "OLED screen", "5G"]])   # a two-link menu is noise

    def test_the_tool_marks_the_page_as_outside_content_and_fails_honestly_without_tables(self):
        with patch.object(internet, "fetch", return_value=(PAGE, "https://shop.example/phones")):
            out = internet._extract({"url": "https://shop.example/phones"}, None)
        self.assertEqual((out.output["table_count"], out.output["provenance"]), (1, "external_untrusted"))
        with patch.object(internet, "fetch", return_value=("<p>just text</p>", "https://x.example")):
            self.assertIn("error", internet._extract({"url": "https://x.example"}, None).output)
        from chutku.agent_loop import TAINTING_TOOLS
        self.assertIn("browser.extract", TAINTING_TOOLS)


if __name__ == "__main__":
    unittest.main()
