"""Z3 (2026-11-06): "pause youtube in brave" and friends are instant, and reach the named app's media session.

Owner: "pause krne me aur baaki cheezon me kaafi time lag raha tha, instant hona chahiye". In the real log the phrase
went through the planner (keyboard.keys, screen.understand, windows.list, windows.manage)."""
import time
import unittest
from unittest.mock import patch

from chutku.tools import everyday
from tests.test_daily_intent import steps


class InstantMediaPhraseTests(unittest.TestCase):
    def test_app_media_phrases_are_one_instant_step(self):
        cases = {
            "pause youtube in brave": {"action": "pause", "app": "brave"},
            "pause the youtube video": {"action": "pause", "app": "browser"},
            "resume youtube": {"action": "play", "app": "browser"},
            "pause spotify": {"action": "pause", "app": "spotify"},
            "skip the song on spotify": {"action": "next", "app": "spotify"},
            "youtube pause karo": {"action": "pause", "app": "browser"},
            "brave mein video roko": {"action": "pause", "app": "brave"},
            "youtube video pause kar do": {"action": "pause", "app": "browser"},
            "spotify ka gaana band karo": {"action": "pause", "app": "spotify"},
            "spotify pe agla gaana": {"action": "next", "app": "spotify"},
            "youtube resume karo": {"action": "play", "app": "browser"},
            "chrome mein video pause karo": {"action": "pause", "app": "chrome"},
        }
        started = time.perf_counter()
        wrong = {}
        for text, arguments in cases.items():
            got = steps(text)
            spotify_skill = arguments["app"] == "spotify" and got and len(got) == 1 and \
                got[0][0] == f"app.spotify.{arguments['action'].replace('play', 'resume')}"
            if got != [("media.control", arguments)] and not spotify_skill:   # (Spotify's own verified actions win)
                wrong[text] = got
        seconds = time.perf_counter() - started
        self.assertEqual(wrong, {})
        self.assertLess(seconds, 1.0)
        print(f"\n[Z3] {len(cases)} app media phrases routed in {seconds * 1000:.0f} ms")

    def test_the_short_forms_the_voice_model_is_told_to_use_are_instant(self):
        from chutku.voice.live import PERSONA
        line = next(l for l in PERSONA.splitlines() if "pause youtube in brave" in l)
        for form in (part.strip() for part in line.split("|")):
            result = steps(form)
            self.assertTrue(result and len(result) == 1 and result[0][0] in {
                "media.control", "app.spotify.pause", "app.spotify.next", "app.spotify.previous"}, (form, result))

    def test_what_must_not_become_a_media_step(self):
        self.assertNotEqual(steps("spotify band karo"), [("media.control", {"action": "pause", "app": "spotify"})])
        self.assertNotIn(("media.control", {"action": "pause", "app": "browser"}), steps("stop") or [])
        for text in ("youtube pe lofi chalao", "play lofi on youtube in brave", "pause"):
            result = steps(text) or []
            self.assertFalse(any(isinstance(s, tuple) and s[1].get("app") for s in result), text)


class MediaControlTargetTests(unittest.TestCase):
    def test_the_named_app_is_matched_and_a_missing_app_fails_honestly(self):
        calls = []

        def fake(script, request):
            calls.append(request)
            if request.get("match") == ["spotify"]:
                return {"session": False}
            return {"session": True, "app": "Brave", "status": "Paused", "title": "t", "accepted": True,
                    "before": {"session": True, "status": "Playing", "title": "t"}}
        with patch.object(everyday, "_powershell", fake):
            ok = everyday._media_control({"action": "pause", "app": "brave"}, None)
            missing = everyday._media_control({"action": "pause", "app": "spotify"}, None)
        self.assertEqual((ok.verification, ok.output["before"], ok.output["after"]),
                         (everyday.Verification.PASS, "Playing", "Paused"))
        self.assertEqual(calls[0], {"action": "pause", "match": ["brave"]})   # one call: before + act + after
        self.assertEqual(missing.verification, everyday.Verification.FAIL)
        self.assertIn("spotify", missing.output["error"].casefold())

    def test_unknown_apps_and_extra_arguments_are_refused(self):
        everyday._validate_media({"action": "pause"})
        everyday._validate_media({"action": "pause", "app": "brave"})
        for bad in ({"action": "pause", "app": "notepad.exe"}, {"action": "pause", "extra": 1}, {"app": "brave"}):
            with self.assertRaises(ValueError):
                everyday._validate_media(bad)


if __name__ == "__main__":
    unittest.main()
