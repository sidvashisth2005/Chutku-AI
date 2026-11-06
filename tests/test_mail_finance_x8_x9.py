"""Phase 6 X8 (email, draft first) and X9 (stock quotes). The network, the mail app and SMTP are always mocked."""
import io
import json
from pathlib import Path
import smtplib
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.parse

from chutku import mind
from chutku.app import create_runtime
from chutku.core.capability_grants import validate_capability
from chutku.quick_intents import quick_proposal
from chutku.tools import finance, internet, mail
from chutku.tools.registry import ExecutionContext

NOW = 1_762_336_740   # 2025-11-05 15:29 IST (09:59 UTC)


def chart(symbol, price, previous, name, currency="INR", when=NOW, offset=19800, zone="IST"):
    return json.dumps({"chart": {"result": [{"meta": {
        "symbol": symbol, "longName": name, "currency": currency, "regularMarketPrice": price,
        "chartPreviousClose": previous, "regularMarketTime": when, "gmtoffset": offset, "timezone": zone,
        "exchangeName": "NSI"}}], "error": None}})


def search(*symbols):
    return json.dumps({"quotes": [{"symbol": s, "quoteType": "EQUITY", "shortname": s} for s in symbols]})


class Fetches:
    """A stand-in for internet.fetch: answers by URL and records every URL asked for."""
    def __init__(self, answers):
        self.answers, self.urls = answers, []

    def __call__(self, url, **_kw):
        self.urls.append(url)
        for part, body in self.answers.items():
            if part in url:
                if isinstance(body, Exception):
                    raise body
                return body, url
        raise AssertionError(f"unexpected URL {url}")


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.patches = [patch.object(mind, "PROJECT_ROOT", base), patch.object(finance, "CACHE", base / "fin.json")]
        for item in self.patches:
            item.start()
        self.runtime = create_runtime(base)

    def tearDown(self):
        self.runtime.close()
        for item in self.patches:
            item.stop()
        self.temp.cleanup()


class FinanceTests(Base):
    def setUp(self):
        super().setUp()
        self.runtime.capability_grants.grant("internet.read")

    def quote(self, query, answers):
        fetches = Fetches(answers)
        with patch.object(internet, "fetch", fetches), patch("time.time", return_value=NOW + 60):
            return self.runtime.run("finance.quote", {"query": query}), fetches.urls

    def test_indian_name_prefers_nse_and_states_the_time(self):
        result, urls = self.quote("infosys", {"/search": search("INFY", "INFY.BO", "INFY.NS"),
                                              "/chart/INFY.NS": chart("INFY.NS", 1520.0, 1500.0, "Infosys Limited")})
        self.assertEqual(result["state"], "COMPLETED")
        self.assertIn("q=infosys", urls[0])
        self.assertIn("/chart/INFY.NS", urls[1])
        expected = round((1520.0 - 1500.0) / 1500.0 * 100, 2)   # independent: +1.33%
        self.assertEqual(result["output"]["quote"]["change_percent"], expected)
        self.assertEqual(result["output"]["reply"], "Infosys Limited (INFY.NS) ₹1,520.00, +1.33%, as of 15:29 IST.")
        self.assertFalse(result["output"]["stale"])

    def test_exact_tickers_win_and_nse_name_match_beats_a_foreign_ticker(self):
        result, urls = self.quote("AAPL", {"/search": search("AAPL", "APC.F"),
                                           "/chart/AAPL": chart("AAPL", 270.5, 268.0, "Apple Inc.", "USD", NOW,
                                                                -18000, "EST")})
        self.assertIn("/chart/AAPL?", urls[1])
        self.assertIn("Apple Inc. (AAPL) $270.50, +0.93%, as of 04:59 EST", result["output"]["reply"])
        result, urls = self.quote("TCS", {"/search": search("TCS", "TCS.NS"),   # NYSE "TCS" is another company
                                          "/chart/TCS.NS": chart("TCS.NS", 3050.0, 3100.0, "Tata Consultancy")})
        self.assertIn("/chart/TCS.NS", urls[1])
        self.assertIn("-1.61%", result["output"]["reply"])

    def test_an_exact_listing_skips_the_search(self):
        result, urls = self.quote("reliance.ns", {"/chart/RELIANCE.NS": chart("RELIANCE.NS", 2950.1, 2915.0,
                                                                              "Reliance Industries Limited")})
        self.assertEqual(len(urls), 1)
        self.assertEqual(result["output"]["reply"],
                         "Reliance Industries Limited (RELIANCE.NS) ₹2,950.10, +1.20%, as of 15:29 IST.")

    def test_offline_answers_from_the_cache_and_says_so(self):
        self.quote("reliance", {"/search": search("RELIANCE.NS"),
                                "/chart/": chart("RELIANCE.NS", 2950.1, 2915.0, "Reliance Industries Limited")})
        self.assertIn("RELIANCE.NS", json.loads(finance.CACHE.read_text(encoding="utf-8"))["quotes"])
        offline = OSError("The site could not be reached (offline or slow).")
        for query in ("Reliance", "RELIANCE.NS"):   # by the name asked before, or by the symbol
            result, _ = self.quote(query, {"/": offline})
            self.assertEqual(result["state"], "COMPLETED", query)
            self.assertTrue(result["output"]["stale"])
            self.assertTrue(result["output"]["reply"].startswith("Offline, last known price: Reliance"), query)
            self.assertIn("as of 15:29 IST", result["output"]["reply"])

    def test_nothing_cached_and_offline_says_no_price_is_known(self):
        result, _ = self.quote("wipro", {"/": OSError("The site could not be reached (offline or slow).")})
        self.assertEqual(result["state"], "FAILED")
        self.assertIn("No price is known for wipro", result["output"]["error"])
        result, _ = self.quote("zzzz nothing", {"/search": json.dumps({"quotes": []})})
        self.assertEqual(result["state"], "FAILED")
        self.assertIn("knows no listed company", result["output"]["error"])

    def test_an_old_price_carries_its_date(self):
        quote = json.loads(chart("X.NS", 10.0, 10.0, "X"))["chart"]["result"][0]["meta"]
        cached = {"symbol": "X.NS", "name": "X", "price": 10.0, "currency": "INR", "change_percent": 0.0,
                  "market_time": quote["regularMarketTime"], "utc_offset_s": 19800, "zone": "IST"}
        self.assertTrue(finance.say(cached, now=NOW + 2 * 86400).endswith("as of 15:29 IST on 05 Nov 2025"))

    def test_the_cache_is_bounded(self):
        with patch.object(finance, "MAX_SYMBOLS", 3), patch.object(finance, "MAX_NAMES", 3):
            for index in range(5):
                finance._remember(f"name {index}", {"symbol": f"S{index}.NS", "fetched": index})
        data = json.loads(finance.CACHE.read_text(encoding="utf-8"))
        self.assertEqual(set(data["quotes"]), {"S2.NS", "S3.NS", "S4.NS"})
        self.assertEqual(list(data["names"]), ["name 2", "name 3", "name 4"])

    def test_contract_and_capability(self):
        tool = self.runtime.registry.get("finance.quote")
        self.assertEqual((int(tool.base_risk), tool.required_capability, tool.network_egress),
                         (0, "internet.read", True))
        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:   # nothing granted
            with patch.object(internet, "fetch") as fetch:
                self.assertEqual(runtime.run("finance.quote", {"query": "TCS"})["state"], "DENIED")
            fetch.assert_not_called()

    def test_instant_phrases(self):
        for phrase, query in (("reliance ka share price", "reliance"), ("TCS stock kitna hai", "TCS"),
                              ("price of AAPL", "AAPL"), ("bhai reliance ka share price batao", "reliance"),
                              ("what is the share price of HDFC Bank", "HDFC Bank")):
            step = quick_proposal(phrase)["next_steps"][0]
            self.assertEqual((step["tool"], step["arguments"]), ("finance.quote", {"query": query}), phrase)
        for phrase in ("price of rice", "price of iphone 16", "mera share kitna hai", "share market kaisa hai"):
            proposal = quick_proposal(phrase)
            self.assertFalse(proposal and proposal["next_steps"][0]["tool"] == "finance.quote", phrase)


class MailTests(Base):
    def setUp(self):
        super().setUp()
        self.runtime.capability_grants.grant("apps.launch")
        mind.default().remember_person("Mummy", aliases=["mammi"], email="mom@example.com")
        mind.default().remember_person("Rohit", relation="brother")   # known, but no email saved

    def draft(self, arguments):
        with patch.object(mail, "mail_handler", return_value="Outlook.URL.mailto.15"), \
                patch("os.startfile") as startfile:
            return self.runtime.run("email.draft", arguments), startfile

    def test_draft_opens_a_mailto_link_and_sends_nothing(self):
        result, startfile = self.draft({"to": "mammi", "subject": "Dinner & plans", "body": "Hi Ma,\nsee you at 8"})
        self.assertEqual(result["state"], "COMPLETED")
        url = startfile.call_args.args[0]
        self.assertTrue(url.startswith("mailto:mom@example.com?subject="))
        parts = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(parts["subject"], ["Dinner & plans"])                  # one field, not an extra parameter
        self.assertEqual(parts["body"], ["Hi Ma,\r\nsee you at 8"])
        self.assertFalse(result["output"]["sent"])
        self.assertIn("cannot attach files", result["output"]["note"])

    def test_draft_text_cannot_add_hidden_recipients(self):
        result, startfile = self.draft({"to": "a@b.co", "subject": "x&bcc=evil@x.io", "body": "y&cc=evil@x.io"})
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(startfile.call_args.args[0]).query)
        self.assertEqual(set(query), {"subject", "body"})
        for bad in ("a@b.co?bcc=evil@x.io", "a@b.co,evil@x.io", "a%40b.co"):
            result, startfile = self.draft({"to": bad, "subject": "s", "body": "b"})
            self.assertEqual(result["state"], "FAILED", bad)
            startfile.assert_not_called()

    def test_unknown_or_address_less_people_ask_instead_of_guessing(self):
        result, startfile = self.draft({"to": "Priya", "subject": "s", "body": "b"})
        self.assertEqual(result["state"], "FAILED")
        self.assertIn("won't guess", result["output"]["error"])
        startfile.assert_not_called()
        result, startfile = self.draft({"to": "Rohit", "subject": "s", "body": "b"})
        self.assertIn("I know Rohit but not their email", result["output"]["error"])
        startfile.assert_not_called()

    def test_no_mail_app_fails_clearly(self):
        with patch.object(mail, "mail_handler", return_value=None), patch("os.startfile") as startfile:
            result = self.runtime.run("email.draft", {"to": "mammi", "subject": "s", "body": "b"})
        self.assertIn("no default mail app", result["output"]["error"])
        startfile.assert_not_called()

    def test_saved_emails_are_validated(self):
        for bad in ("not-an-email", "a@b", "x?cc=y@z.com@q.io", "a b@c.com"):
            with self.assertRaises(ValueError, msg=bad):
                mind.default().remember_person("Bad", email=bad)
        result = self.runtime.run("mind.person", {"name": "Rohit", "email": "rohit.k+1@mail.co.in"})
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(mind.default().find_person("brother")["email"], "rohit.k+1@mail.co.in")

    # -- email.send ------------------------------------------------------------------------
    def ask_send(self, to="mammi", **kw):
        return self.runtime.run("email.send", {"to": to, "subject": "Hello", "body": "Reaching home at 8."}, **kw)

    def test_send_needs_a_capability_that_is_not_granted_by_default(self):
        with patch("smtplib.SMTP_SSL") as smtp:
            self.assertEqual(self.ask_send()["state"], "DENIED")
        smtp.assert_not_called()
        self.assertNotIn("email.send", [g.capability for g in self.runtime.capability_grants.list()])
        self.assertEqual(validate_capability("email.send"), "email.send")   # a real, grantable capability

    def test_every_send_waits_for_the_owner_in_every_mode(self):
        self.runtime.capability_grants.grant("email.send")
        with patch("smtplib.SMTP_SSL") as smtp:
            plain = self.ask_send()
            owner = self.ask_send(provenance="delegated", autonomy="owner")
        smtp.assert_not_called()
        for result in (plain, owner):
            self.assertEqual(result["state"], "WAITING_CONFIRMATION")
            self.assertEqual(result["approval"]["arguments"]["body"], "Reaching home at 8.")   # the card shows it
        self.assertIn("goes to Mummy", owner["reason"])
        with patch("smtplib.SMTP_SSL") as smtp:   # denied on screen: nothing is sent
            denied = self.runtime.approve(owner["approval"]["token"], cancel=True)
        self.assertEqual(denied["state"], "DENIED")
        smtp.assert_not_called()

    def test_approved_send_goes_to_the_resolved_address(self):
        self.runtime.capability_grants.grant("email.send")
        token = self.ask_send()["approval"]["token"]
        server = MagicMock()
        server.send_message.return_value = {}
        with patch.object(mail, "account", return_value=("me@gmail.com", "abcdabcdabcdabcd")), \
                patch("smtplib.SMTP_SSL") as smtp:
            smtp.return_value.__enter__.return_value = server
            result = self.runtime.approve(token)
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(smtp.call_args.args[:2], ("smtp.gmail.com", 465))
        server.login.assert_called_once_with("me@gmail.com", "abcdabcdabcdabcd")
        sent = server.send_message.call_args.args[0]
        self.assertEqual((sent["To"], sent["From"], sent["Subject"]), ("mom@example.com", "me@gmail.com", "Hello"))
        self.assertEqual(sent.get_content().strip(), "Reaching home at 8.")

    def test_no_account_or_unknown_recipient_never_sends(self):
        self.runtime.capability_grants.grant("email.send")
        for to, account, words in (("mammi", None, "No email account is set up"),
                                   ("Priya", ("me@gmail.com", "abcdabcdabcdabcd"), "won't guess")):
            token = self.ask_send(to)["approval"]["token"]
            with patch.object(mail, "account", return_value=account), patch("smtplib.SMTP_SSL") as smtp:
                result = self.runtime.approve(token)
            self.assertEqual(result["state"], "FAILED", to)
            self.assertIn(words, result["output"]["error"])
            self.assertFalse(result["output"]["sent"])
            smtp.assert_not_called()

    def test_a_refused_password_is_reported_and_unapproved_calls_refuse(self):
        self.runtime.capability_grants.grant("email.send")
        token = self.ask_send()["approval"]["token"]
        with patch.object(mail, "account", return_value=("me@gmail.com", "abcdabcdabcdabcd")), \
                patch("smtplib.SMTP_SSL") as smtp:
            smtp.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"no")
            result = self.runtime.approve(token)
        self.assertIn("refused the saved app password", result["output"]["error"])
        context = ExecutionContext("t", self.runtime.journal, self.runtime.granted_root, approved=False)
        with patch("smtplib.SMTP_SSL") as smtp:
            direct = self.runtime.registry.get("email.send").execute(
                {"to": "mammi", "subject": "s", "body": "b"}, context)
        self.assertIn("needs your on-screen OK", direct.output["error"])
        smtp.assert_not_called()

    def test_account_is_stored_as_one_credential_and_validated(self):
        with patch("chutku.cloud_planner.store_key") as store:
            mail.store_account(" me@gmail.com ", "abcd efgh ijkl mnop")
        store.assert_called_once_with("me@gmail.com\nabcdefghijklmnop", target="Chutku/Email")
        for address, password in (("nope", "abcdefghijklmnop"), ("me@gmail.com", "short")):
            with self.assertRaises(ValueError):
                mail.store_account(address, password)
        with patch("chutku.cloud_planner.stored_key", return_value="me@gmail.com\nabcdefghijklmnop"):
            self.assertEqual(mail.account(), ("me@gmail.com", "abcdefghijklmnop"))
        for saved in (None, "", "garbage", "me@gmail.com\n"):
            with patch("chutku.cloud_planner.stored_key", return_value=saved):
                self.assertIsNone(mail.account(), saved)

    def test_cli_set_account_and_status(self):
        from chutku import cli
        out = io.StringIO()
        with patch.object(sys, "argv", ["chutku", "email", "set-account"]), patch("builtins.input",
                return_value="me@gmail.com"), patch("getpass.getpass", return_value="abcdabcdabcdabcd"), \
                patch.object(mail, "store_account") as store, \
                patch.object(mail, "account", return_value=("me@gmail.com", "abcdabcdabcdabcd")), \
                patch("sys.stdout", out):
            cli.main()
        store.assert_called_once_with("me@gmail.com", "abcdabcdabcdabcd")
        self.assertIn('"account": "me@gmail.com"', out.getvalue())
        self.assertNotIn("abcdabcdabcdabcd", out.getvalue())   # the password is never printed


if __name__ == "__main__":
    unittest.main()
