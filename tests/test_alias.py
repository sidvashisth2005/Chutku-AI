"""2026-11-08: typing chutku.localhost in a browser opens the dashboard; any other name gets nothing."""
import http.client
import unittest

from chutku import alias


class AliasTests(unittest.TestCase):
    def setUp(self):
        self.server = alias.start(lambda: "http://127.0.0.1:8765/#token=abc", port=0)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, host):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request("GET", "/", headers={"Host": host})
        response = connection.getresponse()
        result = response.status, response.getheader("Location")
        connection.close()
        return result

    def test_the_name_redirects_to_the_dashboard(self):
        self.assertEqual(self.get("chutku.localhost"), (302, "http://127.0.0.1:8765/#token=abc"))
        self.assertEqual(self.get("CHUTKU.localhost:80")[0], 302)

    def test_other_names_get_nothing(self):
        for host in ("evil.example", "localhost", "127.0.0.1", "chutku.localhost.evil.example", ""):
            self.assertEqual(self.get(host), (404, None), host)

    def test_a_busy_port_starts_nothing(self):
        self.assertIsNone(alias.start(lambda: "x", port=self.server.server_port))


if __name__ == "__main__":
    unittest.main()
