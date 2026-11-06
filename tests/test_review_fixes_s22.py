"""Regression tests for the S22 code-review findings (2026-10-06)."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from chutku import rewind, scheduled
from chutku.agent_loop import _NEGATED
from chutku.app import create_runtime
from chutku.core.preferences import Preferences
from chutku.runtime import SESSION
from chutku.tools.registry import ExecutionContext
from chutku.voice import speaker


class RewindReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name) / "state")
        self.sandbox = self.runtime.granted_root

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def write(self, path, content):
        self.assertEqual(self.runtime.run("filesystem.write_text", {"path": path, "content": content})["state"],
                         "COMPLETED")

    def test_last_task_means_the_whole_agent_session(self):
        self.write("before.txt", "an earlier request")
        token = SESSION.set("session-A")
        try:
            self.write("a.txt", "1")
            self.write("b.txt", "2")
            self.write("c.txt", "3")
        finally:
            SESSION.reset(token)
        items = rewind.plan(self.runtime, {"last_task": True})
        self.assertEqual(sorted(i.entry["arguments"]["path"] for i in items), ["a.txt", "b.txt", "c.txt"])

    def test_a_change_after_the_card_was_shown_is_never_undone(self):
        start = datetime.now() - timedelta(seconds=2)
        self.write("x.txt", "approved")
        until = datetime.now().replace(microsecond=0)
        time.sleep(1.1)
        self.write("x.txt", "newer, after the card")       # e.g. a scheduled task while the card waited
        items = rewind.plan(self.runtime, {"since": start.isoformat(), "until": until.isoformat()})
        self.assertIn("after this list was shown", items[0].why)
        self.assertNotIn("ok", [i.status for i in items])      # nothing about x.txt is undone
        context = ExecutionContext("t", self.runtime.journal, self.sandbox, approved=True)
        rewind.execute(self.runtime, items, context)
        self.assertEqual((self.sandbox / "x.txt").read_text(encoding="utf-8"), "newer, after the card")

    def test_rewind_run_needs_the_moment_the_list_was_shown(self):
        result = self.runtime.run("rewind.run", {"today": True})
        self.assertEqual(result["state"], "FAILED")

    def test_each_undo_is_logged(self):
        start = datetime.now() - timedelta(seconds=2)
        self.write("logged.txt", "x")
        items = rewind.plan(self.runtime, {"since": start.isoformat(),
                                           "until": datetime.now().replace(microsecond=0).isoformat()})
        rewind.execute(self.runtime, items, ExecutionContext("t", self.runtime.journal, self.sandbox, approved=True))
        last = self.runtime.action_log.recent(1)[0]
        self.assertEqual((last["tool"], last["arguments"]["rewound_action"]), ("filesystem.undo_last_write",
                                                                                items[0].seq))


class VoiceReviewTests(unittest.TestCase):
    def test_an_old_owner_clip_never_vouches_for_a_new_request(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            path = speaker.voiceprint_path(base)
            path.parent.mkdir(parents=True)
            np.save(path, np.ones(256, dtype=np.float32) / 16)
            Preferences(base).update({"voice_lock": True})
            speaker.note_utterance(b"\x01\x00" * 48000)
            with patch.object(speaker, "embed", return_value=np.ones(256, dtype=np.float32) / 16), \
                    patch.object(speaker, "available", return_value=True):   # the git-ignored model; embed is faked
                self.assertTrue(speaker.verify_recent(base)[0])
            self.assertEqual(speaker.verify_recent(base), (False, None))   # used once: nothing left to vouch
            with patch.object(speaker, "_live_window", return_value=b""), \
                    patch.object(speaker, "embed", side_effect=AssertionError("must not score an old clip")):
                speaker.note_utterance(b"\x01\x00" * 48000)
                self.assertEqual(speaker.verify_recent(base, "live"), (False, None))   # live: only live sound

    def test_a_late_transcript_without_real_speech_is_never_a_yes(self):
        from chutku.voice.live import LiveConversation
        live = LiveConversation.__new__(LiveConversation)
        live.heard_since_question = "हां"
        live.speech_at_question = 10.0
        live.gate = type("Gate", (), {"speech_seconds": 10.0})()   # the noise gate measured no speech
        live._snapshot = lambda: {"status": "waiting_confirmation"}
        live._log_heard = lambda *a: None
        injected = []
        live.inject = injected.append
        live.server = type("S", (), {"confirm_session": lambda *a: (_ for _ in ()).throw(AssertionError("approved"))})()
        live._late_approval()
        self.assertIn("did not hear a clear yes", injected[0])


class SmallReviewTests(unittest.TestCase):
    def test_a_denial_does_not_hide_a_claim_after_it(self):
        self.assertIn("so I deleted report.txt",
                      _NEGATED.sub(" ", "There were no files named draft, so I deleted report.txt"))
        self.assertEqual(_NEGATED.sub(" ", "Nothing was deleted.").strip(" ."), "")

    def test_a_missed_task_does_not_rewrite_the_file_every_tick(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            scheduled.add(base, "send hi", datetime.now() + timedelta(minutes=1))
            scheduled.take_due(base, datetime.now() + timedelta(hours=8))    # missed once: written
            stamp = scheduled._path(base).stat().st_mtime_ns
            time.sleep(0.05)
            scheduled.take_due(base, datetime.now() + timedelta(hours=9))
            self.assertEqual(scheduled._path(base).stat().st_mtime_ns, stamp)

    def test_earned_autonomy_relax_covers_the_exact_file_only(self):
        from chutku.core.ledger import target_key
        self.assertNotEqual(target_key("filesystem.write_text", {"path": r"C:\Users\me\Desktop\notes.txt"}),
                            target_key("filesystem.write_text", {"path": r"C:\Users\me\Documents\thesis.docx"}))


if __name__ == "__main__":
    unittest.main()
