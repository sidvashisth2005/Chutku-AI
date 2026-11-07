"""Release review 2026-11-07: the relay never serves plain HTTP to the world by accident, and a forged
X-Forwarded-For cannot dodge the sign-up limits."""
import unittest
from types import SimpleNamespace

from chutku.relay import server


class ExposureTests(unittest.TestCase):
    def test_plain_http_off_loopback_is_refused_unless_said_so(self):
        for host in ("127.0.0.1", "::1", "localhost"):
            server.check_exposure(host)
        with self.assertRaisesRegex(SystemExit, "Refusing plain HTTP on 0.0.0.0"):
            server.check_exposure("0.0.0.0")
        with self.assertRaises(SystemExit):
            server.check_exposure("192.168.1.20")
        server.check_exposure("0.0.0.0", cert="relay.pem")
        server.check_exposure("0.0.0.0", behind_proxy=True)
        server.check_exposure("0.0.0.0", home_network=True)

    def test_the_default_host_is_loopback(self):
        import inspect
        self.assertEqual(inspect.signature(server.serve).parameters["host"].default, "127.0.0.1")

    def client_ip(self, peer, forwarded, behind_proxy=True):
        handler = SimpleNamespace(client_address=(peer, 5000), headers={"X-Forwarded-For": forwarded},
                                  server=SimpleNamespace(behind_proxy=behind_proxy))
        return server.RelayHandler._client_ip(handler)

    def test_forwarded_for_is_believed_only_from_a_local_proxy(self):
        self.assertEqual(self.client_ip("127.0.0.1", "203.0.113.9"), "203.0.113.9")
        self.assertEqual(self.client_ip("198.51.100.7", "203.0.113.9"), "198.51.100.7")   # a forged header
        self.assertEqual(self.client_ip("127.0.0.1", "203.0.113.9", behind_proxy=False), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
