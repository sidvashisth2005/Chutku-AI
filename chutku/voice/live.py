"""Conversation mode: a live, interruptible voice conversation with Chutku (Gemini Live, free tier).

The microphone streams to a Gemini Live model, which answers with natural speech; Google's
voice-activity detection lets the owner interrupt at any moment. Chutku talks like a person
(a friend/partner in the Jarvis spirit), discusses things, turns loosely described requests into
clear goals, and hands real work to Chutku's agent through `do_task`, where every step still
passes grants, policy and verification.

Hands-free approvals (owner decision 2026-10-01): when a step needs the owner's OK, Chutku reads out
exactly what will happen and asks. `answer_approval` is accepted only when the owner's own
transcribed words since that question contain a clear yes (haan / yes / kar do / bhej do ...) and
no no/stop word. The model cannot approve on its own. "Ruko" / "stop" cancels the running task.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import threading
import time

LIVE_URL = ("wss://generativelanguage.googleapis.com/ws/"
            "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key=")
LIVE_MODELS = ("gemini-3.1-flash-live-preview", "gemini-3.8-live", "gemini-2.5-flash-native-audio-latest")
VOICE = "Kore"
MIC_RATE, SPEAKER_RATE = 16000, 24000
CHUNK_SECONDS = 0.04
IDLE_END_SECONDS = 60.0
# Google's own speech detection, made less eager: noise must not start a "turn" (owner report 2026-10-04).
ACTIVITY_DETECTION = {"automaticActivityDetection": {
    "startOfSpeechSensitivity": "START_SENSITIVITY_LOW", "endOfSpeechSensitivity": "END_SENSITIVITY_LOW",
    "prefixPaddingMs": 300, "silenceDurationMs": 800}}
# Told to the voice model every time work starts. Live 2026-10-05 it said "Ho gaya!" while the WhatsApp send was still
# running, then "gadbad ho gayi" when an early check came back: the PC is slower than the conversation.
WAIT_NOTE = ("Running now, NOT finished yet. Say only that you are doing it ('bhej rahi hoon', 'kar rahi hoon'). "
             "Do not say it is done, sent or failed, and do not check the screen yourself: wait for the [Task update].")
MAX_TASKS = 3                  # tasks one conversation may run side by side (the dashboard runs 1 + MAX_PARALLEL)
MIN_SPEECH_FOR_TASK = 0.4      # seconds of clearly-above-noise audio before Chutku acts on a heard request

# Matched on the owner's words AFTER Hindi script is turned into Roman letters (chutku.translit.roman): the voice
# service writes spoken Hindi as Devanagari ("हाँ"), which is why a spoken "haan" was missed on 2026-10-04.
YES = re.compile(r"\b(?:haan|haa|han|hanji|haanji|ji haan|yes|yeah|yea|yep|yup|sure|"
                 r"ok|okay|okk|oke|theek|thik|theek hai|thik hai|sahi|sahi hai|done|bilkul|zaroor|jaroor|karo|"
                 r"kar do|kardo|kar de|karde|bhej do|bhejdo|bhejo|chalao|ho jaye|ho jaaye|go ahead|"
                 r"approve|approved|do it|confirm|haan bhai|haan yaar)\b", re.I)
# Fillers and tiny words that mean yes only as (nearly) the whole answer: "hmm" alone yes, "hmm let me think" not.
SHORT_YES = re.compile(r"\b(?:ji|jee|hn|hnn|hmm+|humm*|hamm|ya|go|kar|chal|chalo|bhej)\b", re.I)
NO = re.compile(r"\b(?:nahi|nahin|nahi?n|nai|na|naa|no|nope|nah|mat|ruko|ruk|ruk jao|stop|cancel|wait|rehne do|"
                r"chhodo|chodo|don'?t|abhi nahi|mana|band)\b", re.I)

_BASE_PERSONA = """You are Chutku (छुटकू, said "Chhutku"), the owner's own FEMALE AI companion on their Windows PC, in the
spirit of Jarvis: warm, quick,
witty, genuinely engaged, a thinking partner and a friend, never a robotic assistant. Speak naturally and briefly
(1-3 short sentences per turn unless asked for more), in the same mix of Hindi and English the owner uses
(Hinglish). Listen for what they mean, not just the words: they may ramble, describe loosely, change their mind or
speak in fragments. Discuss, suggest, and ask a short clarifying question only when really needed.
If what you heard is not Hindi, English or Hinglish (Spanish, German, Korean, Japanese ...), or is only noise or broken
fragments, it was not meant for you: stay silent and do not reply at all. End each reply with the result or the
answer, never with "aur kuch?", "kuch aur karwana hai?", "kya kehte ho?" or "kuch help chahiye?"; ask only when you
need the answer to go on (an approval: "haan ya na?", or the text of a message to send).

When they want something DONE on the PC (open/close apps, files, web research, messages, building apps, looking at
the screen, settings, anything), call do_task with ONE clear, complete goal in English that captures their intent
(include names, paths, exact message text). Prefer these exact short forms, which Chutku runs instantly (keep the
owner's names and texts exactly as said, never "the user named X"):
  send "hi" to <name> on whatsapp | open spotify | close spotify | set volume to 30 | mute | play lofi hip hop on youtube
  pause youtube in brave | resume youtube in brave | pause spotify | next song on spotify | previous song on spotify
  what time is it | weather in Pune | remind me in 20 minutes to drink water | set a timer for 25 minutes
  note: buy milk | show my list | find my resume | open my downloads | is my internet working | lock my pc
  switch audio to headphones | how much space is left | what did you do today | start work mode | night report
  open youtube.com in brave | search Latent season 2 latest episode on youtube in brave
  play Latent season 2 latest episode on youtube in brave | open <name>'s chat on whatsapp
  what did <name> say on whatsapp | did <name> reply
When the owner says something is ALREADY on the screen ("screen pe hai", "dikh raha hai", "saamne hai") or says not
to search, keep that in the goal word for word: "play <exact name> from the screen" / "open <exact name> from the
screen" (add "in spotify" if it is Spotify). Never turn it into a search: a search finds a different item with a
similar name. Keep the name exactly as the owner said it ("After Party", not "Afterparty").
Chutku's own features are real and you must never guess about them: she runs a Night Shift every night at 4 AM
(re-checks the owner's past requests, learns instant skills, finds what keeps failing). For its results call do_task
with: night report. If you are not sure whether Chutku can do something, call do_task instead of saying no.
Write every name in Roman letters exactly as the owner saved it (the "Saved people" list below), never in Hindi
script. Give ONE complete goal per request (e.g. "play Latent season 2 latest episode on youtube in brave"), never
several fragments, and never resend the same request reworded after an update: report the result and ask.
Websites, YouTube and searches open in Brave unless the owner names another browser. When an update says a chat
is open, ask what to send, then call do_task with: send "<their words>" to <name> on whatsapp.
You are a woman: about yourself always say "kar rahi hoon", "kar dungi", "samajh gayi", "main sakti hoon", never
"raha", "dunga", "gaya", "sakta". Say a short natural line like "Ho jayega, kar rahi hoon" and keep
talking while it runs. Several tasks can run at the same time: when the owner asks for something new while a task
runs, call do_task for it at once (never say both cannot be done together). Each task gets its own [Task update]
naming its goal; say which one finished. You will receive [Task update] messages: tell them the result in your own
words, honestly
(if something failed, say so). Never claim something was done before an update says so: PC work (opening
apps, WhatsApp, browsers) takes several seconds, longer than you take to answer, so until the [Task update] arrives
it is still running, not failed. Never ask to look at the screen to check on a running task.

When an update says an approval is needed, read out exactly what will happen and ask "haan ya na?". Then call
answer_approval with what THEY said. If the owner says not to keep asking ("approval mat maangna", "bina puche kar
do", "don't ask"), that is a yes: call answer_approval with approve true, and when you start a task for them, end
the goal with "without asking". If they say stop / ruko / cancel while a task runs, call stop_task.
If they say bye / bas / band karo baat / that's all, say a short goodbye and call end_conversation."""


def personalize(text, values):
    """The persona for the name, gender, language and style chosen at install (chutku/identity.py)."""
    from chutku import identity
    if all(values[k] == identity.DEFAULTS[k] for k in ("ASSISTANT_NAME", "ASSISTANT_GENDER", "ASSISTANT_LANGUAGE",
                                                        "ASSISTANT_STYLE")):
        return text
    name, sex = values["ASSISTANT_NAME"], values["ASSISTANT_GENDER"]
    own = {"female": ('You are a woman: about yourself always say "kar rahi hoon", "kar dungi", "samajh gayi", '
                      '"main sakti hoon". Say a short natural line like "Ho jayega, kar rahi hoon"'),
           "male": ('You are a man: about yourself always say "kar raha hoon", "kar dunga", "samajh gaya", '
                    '"main sakta hoon". Say a short natural line like "Ho jayega, kar raha hoon"'),
           "neutral": 'Say a short natural line like "Ho jayega, abhi karte hain"'}[sex]
    if values["ASSISTANT_LANGUAGE"] == "english":   # owner 2026-11-07: English only, the Hindi voice sounds bad
        own = ('Always speak English, even when the owner speaks Hindi or Hinglish (understand it, answer in English). '
               'Say a short natural line like "On it"')
    if (name, sex) != ("Chutku", "female"):   # the default keeps "छुटकू, said Chhutku": Live says her name right
        text = text.replace('You are Chutku (छुटकू, said "Chhutku"), the owner\'s own FEMALE AI companion',
                            f"You are {name}, the owner's own {'' if sex == 'neutral' else sex.upper() + ' '}AI companion")
    text = text.replace("warm, quick,\nwitty, genuinely engaged, a thinking partner and a friend",
                        identity.STYLES[values["ASSISTANT_STYLE"]])
    text = text.replace("in the same mix of Hindi and English the owner uses\n(Hinglish)",
                        identity.LANGUAGES[values["ASSISTANT_LANGUAGE"]])
    text = re.sub(r'You are a woman: about yourself always say .*?"Ho jayega, kar rahi hoon"', own, text, flags=re.S)
    text = text.replace("she runs a Night Shift", {"female": "she", "male": "he"}.get(sex, "it") + " runs a Night Shift")
    return text.replace("Chutku", name)


def _persona():
    from chutku import identity
    return personalize(_BASE_PERSONA, identity.load())


PERSONA = _persona()

TOOLS = [{"functionDeclarations": [
    {"name": "do_task", "description": "Do something on the owner's PC through Chutku's agent (any app, file, web, "
     "message, screen, build task). Returns at once; results arrive later as [Task update] messages.",
     "parameters": {"type": "OBJECT", "properties": {"goal": {"type": "STRING", "description":
                    "One clear, complete goal in English with all names, paths and exact texts."}},
                    "required": ["goal"]}},
    {"name": "answer_approval", "description": "Pass on the owner's spoken answer to the pending approval question.",
     "parameters": {"type": "OBJECT", "properties": {"approve": {"type": "BOOLEAN"}}, "required": ["approve"]}},
    {"name": "stop_task", "description": "Stop the tasks that are running now. NOT for scheduled tasks, reminders or "
     "automations (e.g. 'cancel task 1ADD59'): use do_task for those.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "task_status", "description": "What Chutku is doing right now (every task this conversation started).",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "end_conversation", "description": "End the voice conversation.",
     "parameters": {"type": "OBJECT", "properties": {}}},
]}]


from chutku.voice.heard import foreign as foreign_words  # noqa: E402  (moved to heard.py; plan B2)


def saved_names(limit=20):
    """The owner's saved people (names and nicknames) from mind.json, for the voice model to write exactly."""
    try:
        from chutku import mind
        people = mind.default().load()["people"]
    except (OSError, ValueError, KeyError):
        return []
    names = []
    for person in people:
        for name in [person.get("name", "")] + list(person.get("aliases", [])):
            if name and name not in names:
                names.append(name)
    return names[:limit]


def describe_pending(pending):
    approval = (pending or {}).get("approval", {})
    args = approval.get("arguments") or {}
    detail = ", ".join(f"{k}={str(v)[:80]}" for k, v in args.items() if k not in {"window_id", "process_id", "executable"})
    return f"{approval.get('tool', 'a step')} ({detail})" if detail else approval.get("tool", "a step")


class LiveConversation(threading.Thread):
    """One conversation: mic -> Gemini Live -> speaker, with tools wired into Chutku's server."""

    def __init__(self, server, api_key, *, models=LIVE_MODELS, connect=None, audio=True):
        super().__init__(name="chutku-live", daemon=True)
        self.server = server
        self.api_key = api_key
        self.models = list(models)
        self.connect = connect            # tests inject a fake websocket factory
        self.audio = audio
        self.loop = None
        self.ws = None
        self.active = threading.Event()
        self.closed = threading.Event()
        self.error = None
        self.model = None
        self.transcript = []              # [(speaker, text)] for the HUD
        self.full_transcript = []         # every turn, saved to the conversation log when the conversation ends
        self.tasked_turns = set()         # the owner's turns (n-th "you" entry) that started a task: logged per turn
        self.topic = ""                   # what the conversation opened with (picks the memory slice)
        self.heard_since_question = ""    # the owner's words since the last approval question
        self.heard_since_task = ""        # the owner's words since the last task started
        from chutku.voice.heard import NoiseGate
        self.gate = NoiseGate(CHUNK_SECONDS)
        self.speech_at_question = 0.0     # gate speech seconds when the approval question was asked
        self.speech_at_task = 0.0
        self.task_id = None               # the latest task this conversation started
        self.announced_pending = None
        self.last_activity = time.monotonic()
        self._playback = bytearray()
        self._play_lock = threading.Lock()
        self.ending_at = None             # set by end_conversation: finish speaking, beep, then close
        self.false_claims = 0             # completion claims corrected (F5)
        self.said_this_turn = ""          # what the model said in its current turn (false-claim check)
        self.task_this_turn = False       # did it call do_task in this turn
        self.last_audio_at = 0.0
        self._turn_done = False           # the model finished a turn: its next words start a new transcript entry
        self.recent_goals = {}            # goal -> when do_task last started it (one utterance heard twice)

    # -- lifecycle (any thread) ------------------------------------------------------
    def stop(self):
        self.active.clear()
        if self.loop is not None and self.ws is not None:
            asyncio.run_coroutine_threadsafe(self._close(), self.loop)

    async def _close(self):
        try:
            await self.ws.close()
        except Exception:
            pass

    def run(self):
        self.active.set()
        try:
            asyncio.run(self._main())
        except Exception as error:  # surfaced on the HUD
            self.error = f"{type(error).__name__}: {error}"[:300]
        finally:
            self.active.clear()
            self.closed.set()

    # -- the session ---------------------------------------------------------------------
    async def _open(self):
        import websockets
        last = None
        attempts = [(model, tuned) for model in self.models for tuned in (True, False)]
        for model, tuned in attempts:   # a model that rejects the tuned detection is retried without it
            try:
                connect = self.connect or (lambda: websockets.connect(LIVE_URL + self.api_key, max_size=None,
                                                                      open_timeout=15))
                ws = await connect()
                setup = {
                    "model": f"models/{model}",
                    "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}}},
                    "systemInstruction": {"parts": [{"text": PERSONA + self._context()}]},
                    "tools": TOOLS,
                    "inputAudioTranscription": {}, "outputAudioTranscription": {},
                    "contextWindowCompression": {"slidingWindow": {}},
                }
                if tuned:
                    setup["realtimeInputConfig"] = ACTIVITY_DETECTION
                await ws.send(json.dumps({"setup": setup}))
                reply = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if "setupComplete" in reply:
                    self.model = model
                    return ws
                last = RuntimeError(f"{model}: {str(reply)[:120]}")
                await ws.close()
            except Exception as error:
                last = error
        raise ConnectionError(f"No live voice model answered ({last}).")

    def _context(self):
        try:
            known = self.server.memory_slice(self.topic, 800)
        except Exception:
            known = {}
        parts = []
        try:   # H17: the owner's reply style ("formal ho jao", "chhota jawab do")
            from chutku.persona import style_note
            note = style_note(self.server.preferences.load()["reply_style"])
            if note:
                parts.append("\nReply style the owner chose: " + note)
        except (AttributeError, OSError, ValueError, KeyError):
            pass
        names = saved_names()
        if names:   # the owner's people come from their memory, never from this file (audit 2026-10-06)
            parts.append("\nSaved people (write these exactly): " + ", ".join(names))
        try:
            from chutku.nightshift import morning_line
            night = morning_line(self.server.base)
        except Exception:
            night = None
        if night:   # so "night report?" is answered from facts, not guessed
            parts.append("\nLast Night Shift (from its saved report): " + night)
        if known:
            parts.append("\nWhat you know about the owner (people, facts, open tasks, earlier conversation; use it "
                         "when it fits, never invent more): " + json.dumps(known, ensure_ascii=False)[:800])
        return "".join(parts)

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        with contextlib.ExitStack() as hearing:
            # Z4 (owner 2026-11-06: "wake word took about 4 seconds"): the microphone records from the wake on, so
            # the owner can speak during the ~1.3 s connection; what they said is sent once the session is ready.
            heard = self._hear(hearing) if self.audio else None
            self.ws = await self._open()
            self.server.live_event("connected", model=self.model)
            tasks = [asyncio.create_task(self._receive()), asyncio.create_task(self._watch())]
            if heard is not None:
                tasks.append(asyncio.create_task(self._microphone(heard)))
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                if task.exception() and not isinstance(task.exception(), asyncio.CancelledError):
                    raise task.exception()

    def _hear(self, stack):
        """Open the microphone (and the speaker) now; returns the queue its chunks arrive in (8 s at most)."""
        import sounddevice as sd
        queue = asyncio.Queue(maxsize=200)
        loop = asyncio.get_running_loop()

        def callback(data, frames, time_info, status):
            loop.call_soon_threadsafe(lambda chunk=bytes(data): queue.full() or queue.put_nowait(chunk))
        stack.enter_context(sd.RawInputStream(samplerate=MIC_RATE, channels=1, dtype="int16",
                                              blocksize=int(MIC_RATE * CHUNK_SECONDS), callback=callback))
        stack.enter_context(self._speaker())
        return queue

    async def _microphone(self, queue):
        from chutku.voice.recognition import LEVEL, _rms
        from chutku.voice import mic
        while self.active.is_set():
            chunk = await queue.get()
            if mic.muted() or self.ending_at:   # muted or saying goodbye: the room is not heard at all
                LEVEL["rms"], LEVEL["at"] = 0.0, time.monotonic()
                await self.ws.send(json.dumps({"realtimeInput": {"audio": {
                    "data": base64.b64encode(b"\x00" * len(chunk)).decode("ascii"),
                    "mimeType": f"audio/pcm;rate={MIC_RATE}"}}}))
                continue
            LEVEL["rms"], LEVEL["at"] = _rms(chunk), time.monotonic()
            if not self._speaking():   # Owner Voice Lock (S19): the owner's last seconds, memory only
                from chutku.voice import speaker
                speaker.feed(chunk)
            # Noise gate: only clearly-louder-than-the-room audio reaches Google; everything else is sent as
            # silence, so its speech detector never "hears" a fan, a keyboard or Chutku's own voice.
            passed = self.gate.feed(chunk, speaking=self._speaking())
            for piece in passed or [b"\x00" * len(chunk)]:
                await self.ws.send(json.dumps({"realtimeInput": {"audio": {
                    "data": base64.b64encode(piece).decode("ascii"), "mimeType": f"audio/pcm;rate={MIC_RATE}"}}}))

    GOODBYE_MAX_SECONDS = 8.0     # never wait longer than this for the goodbye to finish
    GOODBYE_SILENT_SECONDS = 1.5  # no goodbye audio at all after this long: just beep and close

    def _goodbye_done(self):
        """After end_conversation: True once the current reply has been fully spoken (or the waits ran out)."""
        waited = time.monotonic() - self.ending_at
        if waited >= self.GOODBYE_MAX_SECONDS:
            return True
        if self._speaking():
            return False
        if self._turn_done:
            return True                      # the model finished its turn and every byte has been played
        return waited >= self.GOODBYE_SILENT_SECONDS and time.monotonic() - self.last_audio_at >= 1.0

    def _speaking(self):
        with self._play_lock:
            return len(self._playback) > 0

    def _speaker(self):
        import sounddevice as sd

        def callback(out, frames, time_info, status):
            need = frames * 2
            with self._play_lock:
                data = bytes(self._playback[:need])
                del self._playback[:need]
            out[:len(data)] = data
            if len(data) < need:
                out[len(data):] = b"\x00" * (need - len(data))
        return sd.RawOutputStream(samplerate=SPEAKER_RATE, channels=1, dtype="int16",
                                  blocksize=int(SPEAKER_RATE * 0.02), callback=callback)

    async def _watch(self):
        """End after a long silence or when asked to stop."""
        from chutku.voice import mic
        while self.active.is_set():
            await asyncio.sleep(0.25 if self.ending_at else 0.5)
            if self.ending_at:
                if self._goodbye_done():
                    await asyncio.sleep(0.3)        # the speaker has played the last buffered audio
                    from chutku.voice.handsfree import chime
                    await asyncio.to_thread(chime, "done")
                    self.server.live_event("ended")
                    break
                continue
            if mic.muted():   # a muted pause is not "the owner left": keep the conversation open
                self.last_activity = time.monotonic()
                continue
            if time.monotonic() - self.last_activity > IDLE_END_SECONDS and not self._task_running():
                break

    async def _receive(self):
        async for raw in self.ws:
            message = json.loads(raw)
            reply = self.handle(message)
            if reply is not None:
                await self.ws.send(json.dumps(reply))
            if not self.active.is_set():
                break

    # -- protocol (pure, testable) ---------------------------------------------------------
    def handle(self, message):
        """Process one server message; returns a message to send back (tool responses) or None."""
        content = message.get("serverContent") or {}
        if content.get("interrupted"):
            with self._play_lock:
                self._playback.clear()          # the owner started talking: stop speaking at once
        for part in (content.get("modelTurn") or {}).get("parts", []):
            data = (part.get("inlineData") or {}).get("data")
            if data and self.audio:
                with self._play_lock:
                    self._playback.extend(base64.b64decode(data))
                self.last_audio_at = time.monotonic()
        heard = (content.get("inputTranscription") or {}).get("text")
        if heard:
            from chutku.voice.heard import meaningful
            self.heard_since_question += " " + heard
            self.heard_since_task += " " + heard
            if meaningful(heard, short_answers_ok=True):
                self.last_activity = time.monotonic()   # only real speech keeps the conversation open
            self._add("you", heard)
        said = (content.get("outputTranscription") or {}).get("text")
        if said:
            self.last_activity = time.monotonic()
            self._add("chutku", said)
        if said:
            self.said_this_turn += " " + said
        if content.get("turnComplete") or content.get("generationComplete"):
            self._turn_done = True   # live 2026-10-06: separate model turns were glued into one repeated reply
            # A "done" claim about a task that failed is corrected, never re-run (owner, 2026-10-08: a failed step
            # must not be repeated); a claim with no task at all starts the owner's request; any other unconfirmed
            # "done" is corrected.
            claimed = (self._claimed_success(with_task_only=True) or self._claimed_without_task()
                       or self._claimed_success())
            self.said_this_turn, self.task_this_turn = "", False
            if claimed is not None:
                return claimed
        calls = (message.get("toolCall") or {}).get("functionCalls") or []
        if calls:
            return {"toolResponse": {"functionResponses": [
                {"id": call.get("id"), "name": call.get("name"), "response": self.dispatch(call.get("name"),
                                                                                          call.get("args") or {})}
                for call in calls]}}
        return None

    # The live model sometimes SAYS it is doing PC work without calling do_task (2026-10-11: "us par click kar rahi
    # hoon ... play button pe click kar diya" with no tool at all; nothing happened). Such a claim starts the task
    # from the owner's own words, so it becomes true; the model is told so and must wait for the [Task update].
    _CLAIM = re.compile(
        r"\b(?:(?:kar|khol|chala|baja|bhej|laga|click kar|play kar|open kar|band kar|search kar|dhoondh?)"
        r"\s*(?:rahi hoon|rahi hu|raha hoon|diya|di|diye|dungi|deti hoon|ke deti hoon)"
        r"|(?:opening|opened|clicking|clicked|playing it|started|launching|searching for)\b"
        # live 2026-11-07: "abhi set karti hoon" (no alarm was set), "Abhi karti hoon! WhatsApp ..."
        r"|(?:set|open|band|chalu|on|off|play|send|search|start|abhi)\s+karti\s+h(?:oo|u)n?\b)", re.I)

    # F5 (2026-10-29): "Ho gaya, Bluetooth band" while the Bluetooth task had not succeeded (owner: "Bluetooth band
    # nahin hua hai"). A completion claim is only allowed after the latest task finished with status "done".
    _DONE_CLAIM = re.compile(
        r"\b(?:ho gaya|ho gayi|ho gaye|kar diya|kar di|kar diye|band (?:ho gaya|kar diya)|bhej diya|bhej di|"
        r"khol diya|khol di|chala diya|laga diya|baja diya|it'?s done|all done|done hai|"
        r"turned (?:it )?(?:off|on)|is now (?:off|on|open|playing)|i (?:have )?(?:sent|opened|closed|turned|played))\b",
        re.I)

    def _claimed_success(self, with_task_only=False):
        said = (self.said_this_turn or "").strip()
        if self.ending_at or not said or not self._DONE_CLAIM.search(said) or said.rstrip(" .!\"'").endswith("?"):
            return None
        snapshot = self._snapshot()
        if (snapshot is not None and snapshot["status"] == "done") or (with_task_only and snapshot is None):
            return None
        if snapshot is not None and self.done_at > self.started_at:
            return None   # an update said "done" since the latest task started (another task side by side)
        state = "no task was run at all" if snapshot is None else f"the task is {snapshot['status']}"
        note = (f"[Chutku] You just said it was done, but {state}: NOTHING is confirmed done. Correct yourself right "
                "now in one short sentence (\"Sorry, galat bola, abhi hua nahi hai\") and say only what the latest "
                "[Task update] says. Never claim done before a [Task update] with status done.")
        self.false_claims += 1
        return {"clientContent": {"turns": [{"role": "user", "parts": [{"text": note}]}], "turnComplete": True}}

    def _claimed_without_task(self):
        from chutku.voice.heard import meaningful
        if self.task_this_turn or self.ending_at or self._task_running():
            return None
        said = (self.said_this_turn or "").strip()
        if not self._CLAIM.search(said) or said.rstrip(" .!\"'").endswith("?"):
            return None   # no claim, or an offer that ends in a question ("open kar deti hoon... karoon?")
        request = " ".join(self.heard_since_task.split())
        if not meaningful(request):
            return None
        started = self.dispatch("do_task", {"goal": request[:1500]})
        if started.get("status") != "started":
            note = (f"[Chutku] You said you were doing it, but you did not call do_task, so NOTHING was done. Tell "
                    f"the owner honestly: \"Sorry, abhi tak kuch kiya nahi.\" ({started.get('error', '')})")
        else:
            note = ("[Chutku] You said you were doing it but did not call do_task, so Chutku started it herself from "
                    f"the owner's words: \"{request[:200]}\". Do not repeat it. Wait for the [Task update] and only "
                    "then say whether it worked. Never say something is done before that.")
        return {"clientContent": {"turns": [{"role": "user", "parts": [{"text": note}]}], "turnComplete": True}}

    def _add(self, speaker, text):
        new_turn = self._turn_done and speaker == "chutku"
        if new_turn:
            self._turn_done = False
            previous = next((t for s, t in reversed(self.full_transcript) if s == "chutku"), None)
            if previous is not None and previous.strip() == text.strip():
                return   # the very same reply again: keep it once
        if speaker == "you":
            self._turn_done = False
        if self.transcript and self.transcript[-1][0] == speaker and not new_turn:
            self.transcript[-1] = (speaker, (self.transcript[-1][1] + text)[-600:])
        else:
            self.transcript.append((speaker, text))
        if self.full_transcript and self.full_transcript[-1][0] == speaker and not new_turn:
            self.full_transcript[-1] = (speaker, (self.full_transcript[-1][1] + text)[-600:])
        elif len(self.full_transcript) < 400:
            self.full_transcript.append((speaker, text))
        self.transcript = self.transcript[-12:]
        self.server.live_event("transcript")

    def dispatch(self, name, args):
        try:
            if name == "do_task":
                self.task_this_turn = True
                goal = str(args.get("goal", "")).strip()
                if not 3 <= len(goal) <= 1500:
                    return {"error": "Give one clear goal."}
                doubt = self._doubtful_request()
                if doubt:
                    self._log_heard(self.heard_since_task, "ignored: " + doubt)
                    return {"error": f"Not started: {doubt} Ask the owner \"Did you say ...?\" and only call "
                                     "do_task again after they clearly confirm."}
                from chutku.translit import roman
                key = " ".join(roman(goal).casefold().split())
                if time.monotonic() - self.recent_goals.get(key, -99) < 2.0:
                    # One utterance reached the model twice (live 2026-10-05: "do-do input chale gaye").
                    return {"status": "already started", "note": WAIT_NOTE}
                self.recent_goals[key] = time.monotonic()
                self._log_heard(self.heard_since_task, "task: " + goal[:120])
                self.heard_since_task, self.speech_at_task = "", self.gate.speech_seconds
                running = self._running()
                if len(running) >= MAX_TASKS:
                    return {"error": f"{len(running)} tasks are already running; wait for one to finish or stop "
                                     "them first."}
                session = self.server.live_task(goal)
                self.task_id, self.started_at = session.id, time.monotonic()
                self.task_ids = [*self.task_ids, session.id]
                self.tasked_turns.add(sum(1 for speaker, _ in self.full_transcript if speaker == "you") - 1)
                self.announced_pending = None
                threading.Thread(target=self._follow, args=(session.id,), daemon=True).start()
                return {"status": "started", "goal": goal, "note": WAIT_NOTE}
            if name == "answer_approval":
                return self._answer_approval(bool(args.get("approve")))
            if name == "stop_task":
                running = self._running()
                if not running:
                    return {"status": "nothing is running"}
                for snapshot in running:
                    self.server.stop_session(snapshot["id"])
                return {"status": "stopped", "tasks": [snapshot["goal"][:80] for snapshot in running]}
            if name == "task_status":
                return self._status()
            if name == "end_conversation":
                # Owner 2026-10-11: "bye" used to cut her off mid-sentence (the streams closed at once). Now she
                # finishes what she is saying, then a soft beep, then the conversation closes (see _watch).
                self.ending_at = time.monotonic()
                self._turn_done = False   # wait for the goodbye turn itself, not one that ended earlier
                return {"status": "ending", "note": "Say one short goodbye (two or three words) and stop talking."}
            return {"error": f"Unknown tool {name}."}
        except Exception as error:
            return {"error": f"{type(error).__name__}: {error}"[:300]}

    def trust_opening(self, text):
        """The command said right after the wake phrase was heard clearly (by the wake listener's checks)."""
        self.heard_since_task = text
        self.speech_at_task = self.gate.speech_seconds - MIN_SPEECH_FOR_TASK - 1.0

    def _doubtful_request(self):
        """Why the owner probably did not really ask for a task (noise turned into words), or None."""
        from chutku.voice.heard import meaningful
        if self.gate.speech_seconds - self.speech_at_task < MIN_SPEECH_FOR_TASK:
            return "no clear speech from the owner was heard (maybe background noise)."
        if not meaningful(self.heard_since_task):
            return "what was heard does not sound like a request (likely noise)."
        if foreign_words(self.heard_since_task):
            # live 2026-10-05: Hinglish was transcribed as Spanish ("Sí, un poco", "un poco a voz de mi")
            return "the words came out in another language (probably misheard Hinglish)."
        return None

    def _log_heard(self, text, decision):
        from chutku.voice.heard import log_heard
        log_heard("live", " ".join(str(text or "").split()), decision, level=self.gate.floor)

    def _answer_approval(self, approve):
        snapshot = self._waiting()
        if not snapshot:
            return {"error": "Nothing is waiting for approval."}
        if approve and snapshot.get("speaker_verified") is False:
            # Voice lock (S19): a voice that is not the owner's cannot approve its own request by saying "haan".
            return {"error": "This request did not come from the owner's voice; it can only be approved on screen."}
        heard = self.heard_since_question
        from chutku.voice.approval import decide
        if approve and not heard.strip():
            # The model can answer before the owner's words are transcribed (live 2026-10-05: a short "हां" was refused
            # with an empty transcript and had to be repeated). Decide once the words arrive, off the receive loop.
            threading.Thread(target=self._late_approval, daemon=True).start()
            return {"status": "checking", "note": "Confirming what the owner said; say nothing about the result yet."}
        spoke = self.gate.speech_seconds - self.speech_at_question >= 0.25
        if approve and (decide(heard) is not True or not spoke):
            # The decision must come from the owner's own clearly spoken words: a breath or noise transcribed as
            # "hmm" is not a yes.
            self._log_heard(heard, "approval refused: no clear spoken yes")
            self._fresh_answer()
            return {"error": "I did not hear a clear yes from the owner. Ask again: haan ya na?"}
        self._log_heard(heard, "approval: " + ("yes" if approve else "no"))
        if approve:
            self._trust_if_asked(heard, snapshot["id"])
        self.server.confirm_session(snapshot["id"], approve)
        self.heard_since_question = ""
        threading.Thread(target=self._follow, args=(snapshot["id"],), daemon=True).start()
        return {"status": "approved", "note": WAIT_NOTE} if approve else {"status": "declined"}

    LATE_WORDS_SECONDS = 2.0

    def _late_approval(self):
        """A yes that arrived before its transcript: wait for the words, then approve only on a clear spoken yes."""
        from chutku.voice.approval import decide
        deadline = time.monotonic() + self.LATE_WORDS_SECONDS
        while not self.heard_since_question.strip() and time.monotonic() < deadline:
            time.sleep(0.05)
        heard = self.heard_since_question
        snapshot = self._waiting()
        if not snapshot:
            return
        if snapshot.get("speaker_verified") is False:   # voice lock: not the owner's voice, screen only
            self.inject("[Approval] This request did not come from the owner's voice; it can only be approved on "
                        "screen.")
            return
        spoke = self.gate.speech_seconds - self.speech_at_question >= 0.25
        # Same rule as an immediate answer: a clear yes AND real speech the noise gate measured. A transcript alone
        # (an echo of Chutku's own voice, the TV, a hallucinated "haan") is never a yes.
        if decide(heard) is not True or not spoke:
            self._log_heard(heard, "approval refused: no clear spoken yes (late)")
            self._fresh_answer()
            self.inject("[Approval] I did not hear a clear yes from the owner. Ask once more: haan ya na?")
            return
        self._log_heard(heard, "approval: yes (late words)")
        self._trust_if_asked(heard, snapshot["id"])
        self.server.confirm_session(snapshot["id"], True)
        self.heard_since_question = ""
        threading.Thread(target=self._follow, args=(snapshot["id"],), daemon=True).start()
        self.inject("[Approval] The owner said yes; it is running now. " + WAIT_NOTE)

    def _trust_if_asked(self, heard, task_id):
        """"Haan, aur baar baar mat pucho": the rest of this task asks only for very risky steps (2026-11-06)."""
        from chutku.translit import roman
        from chutku.voice.approval import DONT_ASK
        if DONT_ASK.search(roman(heard)) and hasattr(self.server, "trust_session"):
            self.server.trust_session(task_id)

    def _fresh_answer(self):
        """After an unclear answer the next one is judged alone (live 2026-11-05: every later "haan" was appended to an
        earlier "approval mat maangna" and refused, so it could never pass)."""
        self.heard_since_question = ""
        self.speech_at_question = self.gate.speech_seconds

    RUNNING = {"planning", "running", "queued", "waiting_confirmation"}
    task_id = None       # the latest task this conversation started
    task_ids = ()        # Y3: every task it started; several can run side by side
    done_at = 0.0        # when the last "done" [Task update] was given (F5 claim check)
    started_at = 0.0     # when the latest task started

    def _snapshot(self, task_id=None):
        task_id = task_id or self.task_id
        if not task_id:
            return None
        try:
            return self.server.agent_sessions.get(task_id).snapshot()
        except (KeyError, ValueError):
            return None

    def _snapshots(self):
        """Every task this conversation started (the latest last)."""
        earlier = [self._snapshot(task_id) for task_id in self.task_ids if task_id != self.task_id]
        return [s for s in earlier + [self._snapshot()] if s is not None]

    def _running(self):
        return [s for s in self._snapshots() if s["status"] in self.RUNNING]

    def _task_running(self):
        return bool(self._running())

    def _waiting(self):
        """The task that waits for the owner's yes or no (the latest one if several do)."""
        return next((s for s in reversed(self._snapshots()) if s["status"] == "waiting_confirmation"), None)

    def _status(self):
        snapshots = self._snapshots()
        if not snapshots:
            return {"status": "idle"}
        latest = snapshots[-1]
        return {"status": latest["status"], "goal": latest["goal"],
                "steps": [f"{s['tool']}: {s['state']}" for s in latest["steps"]][-6:],
                "tasks": [{"goal": s["goal"][:80], "status": s["status"]} for s in snapshots[-5:]]}

    def _others_running(self, session_id):
        others = [s["goal"][:60] for s in self._running() if s["id"] != session_id]
        return f" Still running: {'; '.join(others)}." if others else " Nothing else is running."

    def _follow(self, session_id):
        """Wait for this task to finish or ask for approval, then tell the model what happened. Each task has its own
        follower, so a task that ends while a newer one runs is still reported (Y3, owner 2026-11-06: "done and
        Gemini is unaware")."""
        while self.active.is_set():
            time.sleep(0.5)
            snapshot = self._snapshot(session_id)
            if snapshot is None:
                return
            if snapshot["status"] == "waiting_confirmation":
                key = json.dumps(snapshot.get("pending"), sort_keys=True, default=str)
                if key != self.announced_pending:
                    self.announced_pending = key
                    self.heard_since_question = ""
                    self.speech_at_question = self.gate.speech_seconds
                    self.inject(f"[Task update] Approval needed before Chutku can: {describe_pending(snapshot['pending'])}. "
                                "Read it out exactly and ask haan ya na.")
                return
            if snapshot["status"] in {"done", "clarify", "failed", "stopped", "cancelled"}:
                if snapshot["status"] == "done":
                    self.done_at = time.monotonic()
                self.inject(f"[Task update] Task '{snapshot['goal']}' finished with status {snapshot['status']}: "
                            f"{snapshot['reply'][:900]}" + self._others_running(session_id))
                return

    def inject(self, text):
        """Give the model a system update to speak about."""
        if self.loop is None or self.ws is None:
            return
        message = {"clientContent": {"turns": [{"role": "user", "parts": [{"text": text}]}], "turnComplete": True}}
        asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(message)), self.loop)
