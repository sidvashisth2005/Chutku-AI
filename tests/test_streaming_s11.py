"""Streaming first words and server-sent updates (master plan S11)."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import types
import unittest
from unittest.mock import patch

from chutku import dashboard
from chutku.agent_loop import AgentSession, LocalAgentPlanner
from chutku.brain_service import BrainService
from chutku.streaming import AnswerSentences, answer_prefix
from tests import test_dashboard


class SentenceTests(unittest.TestCase):
    def feed_all(self, text, sentences):
        for end in range(1, len(text) + 1):
            sentences.feed(text[:end])
        sentences.feed(text, final=True)

    def test_sentences_come_out_as_they_finish(self):
        said = []
        self.feed_all('{"answer": "Theek hai. Downloads mein 3 files hain! Sabse badi \\"NFL.pdf\\" hai."}',
                      AnswerSentences(said.append))
        self.assertEqual(said, ["Theek hai.", "Downloads mein 3 files hain!", 'Sabse badi "NFL.pdf" hai.'])

    def test_a_false_claim_stops_the_stream(self):
        said = []
        guard = lambda s: None if "deleted" in s else s
        self.feed_all('{"answer": "Done checking. I deleted the old files. All fine."}', AnswerSentences(said.append, guard))
        self.assertEqual(said, ["Done checking."])   # nothing after the bad sentence is spoken

    def test_unfinished_escapes_wait(self):
        self.assertEqual(answer_prefix('{"answer": "a\\'), "a")
        self.assertEqual(answer_prefix('{"answer": "a\\u00e9b'), "aéb")


class FakeModel(BaseHTTPRequestHandler):
    pieces = ['{"answer": "', "Pehla vakya.", " Doosra", ' vakya."}']

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in self.pieces:
            chunk = {"choices": [{"delta": {"content": piece}, "finish_reason": None}]}
            self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
        self.wfile.write(b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\ndata: [DONE]\n\n')

    def log_message(self, *_):
        pass


class StreamCompleteTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.service = BrainService(idle_seconds=60)
        self.service.port, self.service.key = self.server.server_port, "k"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_text_arrives_piece_by_piece_and_parses(self):
        seen = []
        with patch.object(self.service, "ensure_started"):
            raw, meta = self.service.stream_complete([], schema={}, schema_name="x", max_tokens=10, on_text=seen.append)
        self.assertEqual(raw, {"answer": "Pehla vakya. Doosra vakya."})
        self.assertEqual(len(seen), 4)
        self.assertTrue(meta["streamed"])
        self.assertEqual(self.service.inflight, 0)

    def test_a_stop_while_streaming_closes_the_model(self):
        closed = []
        with patch.object(self.service, "ensure_started"), patch.object(self.service, "close", lambda: closed.append(1)):
            def stop():
                raise InterruptedError("stopped")
            with self.assertRaises(InterruptedError):
                self.service.stream_complete([], schema={}, schema_name="x", max_tokens=10, on_text=lambda t: None,
                                             check=stop)
        self.assertEqual(closed, [1])
        self.assertEqual(self.service.inflight, 0)

    def test_the_answer_pass_speaks_sentences_through_the_guards(self):
        session = AgentSession("kitni files hain", mode="owner")
        said = []
        session.on_sentence = said.append
        planner = LocalAgentPlanner(self.service)
        with patch.object(self.service, "ensure_started"):
            answer = planner.answer(session, None)
        self.assertEqual(answer, "Pehla vakya. Doosra vakya.")
        self.assertEqual(said, ["Pehla vakya.", "Doosra vakya."])


class SpeakResultTests(unittest.TestCase):
    def test_a_streamed_answer_is_not_spoken_twice(self):
        session = AgentSession("x", mode="owner", origin="voice")
        session._finish("done", "Pehla vakya.")
        session.streamed = types.SimpleNamespace(spoken=["Pehla vakya."])
        router = types.SimpleNamespace(default=types.SimpleNamespace(run=lambda *a, **k: self.fail("spoke twice")))
        dashboard.speak_result(session, router)


class EventStreamTests(unittest.TestCase):
    setUp = test_dashboard.DashboardTests.setUp
    tearDown = test_dashboard.DashboardTests.tearDown

    def get(self, path, headers=None):
        import http.client
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        connection.request("GET", path, headers=headers if headers is not None else {"X-Chutku-Token": self.server.token})
        response = connection.getresponse()
        return response, connection

    def test_a_finished_task_is_pushed_and_the_stream_ends(self):
        session = self.server.agent_sessions.add(AgentSession("hello", mode="owner"))
        session._finish("done", "Hi!")
        response, connection = self.get(f"/api/events?id={session.id}")
        body = response.read().decode()
        connection.close()
        self.assertEqual(response.status, 200)
        self.assertIn("text/event-stream", response.getheader("Content-Type"))
        event = json.loads(body.split("data: ", 1)[1].split("\n\n")[0])
        self.assertEqual(event["session"]["status"], "done")

    def test_the_stream_needs_the_session_token(self):
        response, connection = self.get("/api/events", headers={})
        connection.close()
        self.assertEqual(response.status, 403)
        response, connection = self.get("/api/events?id=nope")
        connection.close()
        self.assertEqual(response.status, 404)


class SilentLiveTests(unittest.TestCase):
    def test_live_conversation_tasks_never_get_their_own_speech(self):
        server = types.SimpleNamespace(preferences=types.SimpleNamespace(load=lambda: {"handsfree_mode": "owner"}),
                                       hud_state={})
        calls = {}
        server.begin_session = lambda goal, mode, origin, silent=False: calls.update(silent=silent) or \
            types.SimpleNamespace(id="s1")
        dashboard.DashboardServer.live_task(server, "open whatsapp")
        self.assertTrue(calls["silent"])


if __name__ == "__main__":
    unittest.main()
