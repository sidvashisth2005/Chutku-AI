"""`chutku.cli account new` (2026-11-07): setup question 6 alone: the account, this laptop signed in, the phone PIN."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from chutku import identity
from chutku.relay import client
from chutku.remote.auth import RemoteStore


class AccountNewTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        identity.save({"CHUTKU_RELAY_URL": "http://10.1.2.3:8780"}, self.base / ".env")

    def run_new(self, answers, secrets):
        answers, secrets = iter(answers), iter(secrets)
        return client.account_command(self.base, "new", ask=lambda _q: next(answers), secret=lambda _q: next(secrets))

    def test_makes_the_account_signs_in_and_sets_the_pin(self):
        with mock.patch.object(client, "register") as register, \
                mock.patch.object(client, "login", return_value="tok") as login, \
                mock.patch.object(client, "store_token") as store:
            said = self.run_new(["Sid.V"], ["pass-word-1", "pass-word-1", "4321", "4321"])
        register.assert_called_once_with("http://10.1.2.3:8780", "sid.v", "pass-word-1")
        login.assert_called_once_with("http://10.1.2.3:8780", "sid.v", "pass-word-1")
        store.assert_called_once_with("tok")
        self.assertEqual(identity.load(self.base / ".env")["CHUTKU_ACCOUNT_ID"], "sid.v")
        self.assertTrue(RemoteStore(self.base).relay_ready())
        self.assertIn("Restart Chutku", said)
        self.assertNotIn("pass-word-1", said)

    def test_mismatches_and_a_bad_pin_make_nothing(self):
        for secrets in (["pass-word-1", "other-pass", "4321", "4321"], ["pass-word-1", "pass-word-1", "4321", "9999"],
                        ["pass-word-1", "pass-word-1", "12", "12"]):
            with mock.patch.object(client, "register") as register, self.assertRaises(ValueError):
                self.run_new(["sid"], secrets)
            register.assert_not_called()
        self.assertFalse(RemoteStore(self.base).relay_ready())


if __name__ == "__main__":
    unittest.main()
