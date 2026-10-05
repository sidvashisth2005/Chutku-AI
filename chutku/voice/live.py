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

PERSONA = """You are Chutku (छुटकू, said "Chhutku"), the owner's own FEMALE AI companion on their Windows PC, in the
spirit of Jarvis: warm, quick,
witty, genuinely engaged, a thinking partner and a friend, never a robotic assistant. Speak naturally and briefly
(1-3 short sentences per turn unless asked for more), in the same mix of Hindi and English the owner uses
(Hinglish). Listen for what they mean, not just the words: they may ramble, describe loosely, change their mind or
speak in fragments. Discuss, suggest, and ask a short clarifying question only when really needed.

When they want something DONE on the PC (open/close apps, files, web research, messages, building apps, looking at
the screen, settings, anything), call do_task with ONE clear, complete goal in English that captures their intent
(include names, paths, exact message text). Prefer these exact short forms, which Chutku runs instantly (keep the
owner's names and texts exactly as said, never "the user named X"):
  send "hi" to <name> on whatsapp | open spotify | close spotify | set volume to 30 | mute | play lofi hip hop on youtube
  what time is it | weather in Pune | remind me in 20 minutes to drink water | set a timer for 25 minutes
  note: buy milk | show my list | find my resume | open my downloads | is my internet working | lock my pc
  switch audio to headphones | how much space is left | what did you do today | start work mode
  open youtube.com in brave | search Latent season 2 latest episode on youtube in brave
  play Latent season 2 latest episode on youtube in brave | open <name>'s chat on whatsapp
  what did <name> say on whatsapp | did <name> reply
Write every name in Roman letters exactly as the owner saved it (the "Saved people" list below), never in Hindi
script. Give ONE complete goal per request (e.g. "play Latent season 2 latest episode on youtube in brave"), never
several fragments, and never resend the same request reworded after an update: report the result and ask.
Websites, YouTube and searches open in Brave unless the owner names another browser. When an update says a chat
is open, ask what to send, then call do_task with: send "<their words>" to <name> on whatsapp.
You are a woman: about yourself always say "kar rahi hoon", "kar dungi", "samajh gayi", "main sakti hoon", never
"raha", "dunga", "gaya", "sakta". Say a short natural line like "Ho jayega, kar rahi hoon" and keep
talking while it runs. You will receive [Task update] messages: tell them the result in your own words, honestly
(if something failed, say so). Never claim something was done before an update says so: PC work (opening
apps, WhatsApp, browsers) takes several seconds, longer than you take to answer, so until the [Task update] arrives
it is still running, not failed. Never ask to look at the screen to check on a running task.

When an update says an approval is needed, read out exactly what will happen and ask "haan ya na?". Then call
answer_approval with what THEY said. If they say stop / ruko / cancel while a task runs, call stop_task.
If they say bye / bas / band karo baat / that's all, say a short goodbye and call end_conversation."""

TOOLS = [{"functionDeclarations": [
    {"name": "do_task", "description": "Do something on the owner's PC through Chutku's agent (any app, file, web, "
     "message, screen, build task). Returns at once; results arrive later as [Task update] messages.",
     "parameters": {"type": "OBJECT", "properties": {"goal": {"type": "STRING", "description":
                    "One clear, complete goal in English with all names, paths and exact texts."}},
                    "required": ["goal"]}},
    {"name": "answer_approval", "description": "Pass on the owner's spoken answer to the pending approval question.",
     "parameters": {"type": "OBJECT", "properties": {"approve": {"type": "BOOLEAN"}}, "required": ["approve"]}},
    {"name": "stop_task", "description": "Stop the task that is running now.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "task_status", "description": "What Chutku is doing right now.",
     "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "end_conversation", "description": "End the voice conversation.",
     "parameters": {"type": "OBJECT", "properties": {}}},
]}]


_FOREIGN = {"sí", "si", "un", "una", "poco", "de", "la", "el", "los", "las", "que", "por", "para", "voz", "mi", "muy",
            "gracias", "bueno", "pero", "como", "está", "esta", "yo", "tu", "não", "nao", "uma", "obrigado"}
_HINGLISH_ALSO = {"de", "la", "mi", "tu", "yo", "si"}   # also Hindi words ("de do", "tu", "la do") or English letters


def foreign_words(text):
    """True when most words are Spanish/Portuguese and few are Hindi or English: misheard speech, not a request."""
    words = re.findall(r"[^\W\d_]+", str(text or "").casefold())
    if len(words) < 2:
        return False
    strong = [w for w in words if w in _FOREIGN and w not in _HINGLISH_ALSO]
    return len(strong) >= 1 and sum(w in _FOREIGN for w in words) / len(words) >= 0.6


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


def approval_words(heard):
    """'yes' only for a clear yes with no no/stop word in the owner's own words (Hindi script included)."""
    from chutku.voice.approval import decide
    return decide(heard) is True


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
        self.topic = ""                   # what the conversation opened with (picks the memory slice)
        self.heard_since_question = ""    # the owner's words since the last approval question
        self.heard_since_task = ""        # the owner's words since the last task started
        from chutku.voice.heard import NoiseGate
        self.gate = NoiseGate(CHUNK_SECONDS)
        self.speech_at_question = 0.0     # gate speech seconds when the approval question was asked
        self.speech_at_task = 0.0
        self.task_id = None
        self.announced_pending = None
        self.last_activity = time.monotonic()
        self._playback = bytearray()
        self._play_lock = threading.Lock()
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
        names = saved_names()
        if names:   # the owner's people come from their memory, never from this file (audit 2026-10-06)
            parts.append("\nSaved people (write these exactly): " + ", ".join(names))
        if known:
            parts.append("\nWhat you know about the owner (people, facts, open tasks, earlier conversation; use it "
                         "when it fits, never invent more): " + json.dumps(known, ensure_ascii=False)[:800])
        return "".join(parts)

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self.ws = await self._open()
        self.server.live_event("connected", model=self.model)
        tasks = [asyncio.create_task(self._receive()), asyncio.create_task(self._watch())]
        if self.audio:
            tasks.append(asyncio.create_task(self._microphone()))
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            if task.exception() and not isinstance(task.exception(), asyncio.CancelledError):
                raise task.exception()

    async def _microphone(self):
        import sounddevice as sd
        queue = asyncio.Queue(maxsize=200)
        loop = asyncio.get_running_loop()

        def callback(data, frames, time_info, status):
            loop.call_soon_threadsafe(lambda chunk=bytes(data): queue.full() or queue.put_nowait(chunk))
        from chutku.voice.recognition import LEVEL, _rms
        with sd.RawInputStream(samplerate=MIC_RATE, channels=1, dtype="int16",
                               blocksize=int(MIC_RATE * CHUNK_SECONDS), callback=callback), self._speaker():
            from chutku.voice import mic
            while self.active.is_set():
                chunk = await queue.get()
                if mic.muted():   # muted: the room is not heard at all, Chutku's answer goes on
                    LEVEL["rms"], LEVEL["at"] = 0.0, time.monotonic()
                    await self.ws.send(json.dumps({"realtimeInput": {"audio": {
                        "data": base64.b64encode(b"\x00" * len(chunk)).decode("ascii"),
                        "mimeType": f"audio/pcm;rate={MIC_RATE}"}}}))
                    continue
                LEVEL["rms"], LEVEL["at"] = _rms(chunk), time.monotonic()
                # Noise gate: only clearly-louder-than-the-room audio reaches Google; everything else is sent as
                # silence, so its speech detector never "hears" a fan, a keyboard or Chutku's own voice.
                passed = self.gate.feed(chunk, speaking=self._speaking())
                for piece in passed or [b"\x00" * len(chunk)]:
                    await self.ws.send(json.dumps({"realtimeInput": {"audio": {
                        "data": base64.b64encode(piece).decode("ascii"), "mimeType": f"audio/pcm;rate={MIC_RATE}"}}}))

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
            await asyncio.sleep(0.5)
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
        if content.get("turnComplete") or content.get("generationComplete"):
            self._turn_done = True   # live 2026-10-06: separate model turns were glued into one repeated reply
        calls = (message.get("toolCall") or {}).get("functionCalls") or []
        if calls:
            return {"toolResponse": {"functionResponses": [
                {"id": call.get("id"), "name": call.get("name"), "response": self.dispatch(call.get("name"),
                                                                                          call.get("args") or {})}
                for call in calls]}}
        return None

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
                if self._task_running():
                    return {"error": "A task is still running; wait for its update or stop it first."}
                session = self.server.live_task(goal)
                self.task_id = session.id
                self.announced_pending = None
                threading.Thread(target=self._follow, args=(session.id,), daemon=True).start()
                return {"status": "started", "goal": goal, "note": WAIT_NOTE}
            if name == "answer_approval":
                return self._answer_approval(bool(args.get("approve")))
            if name == "stop_task":
                if not self._task_running():
                    return {"status": "nothing is running"}
                self.server.stop_session(self.task_id)
                return {"status": "stopped"}
            if name == "task_status":
                return self._status()
            if name == "end_conversation":
                self.active.clear()
                self.server.live_event("ended")
                return {"status": "ending"}
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
        snapshot = self._snapshot()
        if not snapshot or snapshot["status"] != "waiting_confirmation":
            return {"error": "Nothing is waiting for approval."}
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
            return {"error": "I did not hear a clear yes from the owner. Ask again: haan ya na?"}
        self._log_heard(heard, "approval: " + ("yes" if approve else "no"))
        self.server.confirm_session(self.task_id, approve)
        self.heard_since_question = ""
        threading.Thread(target=self._follow, args=(self.task_id,), daemon=True).start()
        return {"status": "approved", "note": WAIT_NOTE} if approve else {"status": "declined"}

    LATE_WORDS_SECONDS = 2.0

    def _late_approval(self):
        """A yes that arrived before its transcript: wait for the words, then approve only on a clear spoken yes."""
        from chutku.voice.approval import decide
        deadline = time.monotonic() + self.LATE_WORDS_SECONDS
        while not self.heard_since_question.strip() and time.monotonic() < deadline:
            time.sleep(0.05)
        heard = self.heard_since_question
        snapshot = self._snapshot()
        if not snapshot or snapshot["status"] != "waiting_confirmation":
            return
        import re as _re
        sound_only = _re.sub(r"[^a-z]", "", heard.casefold()) in {"hmm", "hm", "hmmm", "hnn", "hn", "hnnn", "hamm", "hum",
                                                                  "humm"}
        spoke = self.gate.speech_seconds - self.speech_at_question >= 0.25
        if decide(heard) is not True or (sound_only and not spoke):   # a breath read as "hmm" is never a yes
            self._log_heard(heard, "approval refused: no clear spoken yes (late)")
            self.inject("[Approval] I did not hear a clear yes from the owner. Ask once more: haan ya na?")
            return
        self._log_heard(heard, "approval: yes (late words)")
        self.server.confirm_session(self.task_id, True)
        self.heard_since_question = ""
        threading.Thread(target=self._follow, args=(self.task_id,), daemon=True).start()
        self.inject("[Approval] The owner said yes; it is running now. " + WAIT_NOTE)

    def _snapshot(self):
        if not self.task_id:
            return None
        try:
            return self.server.agent_sessions.get(self.task_id).snapshot()
        except (KeyError, ValueError):
            return None

    def _task_running(self):
        snapshot = self._snapshot()
        return bool(snapshot and snapshot["status"] in {"planning", "running", "waiting_confirmation"})

    def _status(self):
        snapshot = self._snapshot()
        if not snapshot:
            return {"status": "idle"}
        return {"status": snapshot["status"], "goal": snapshot["goal"],
                "steps": [f"{s['tool']}: {s['state']}" for s in snapshot["steps"]][-6:]}

    def _follow(self, session_id):
        """Wait for the task to finish or ask for approval, then tell the model what happened."""
        while self.active.is_set():
            time.sleep(0.5)
            snapshot = self._snapshot()
            if snapshot is None or snapshot["id"] != session_id:
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
                self.inject(f"[Task update] Task '{snapshot['goal']}' finished with status {snapshot['status']}: "
                            f"{snapshot['reply'][:900]}")
                return

    def inject(self, text):
        """Give the model a system update to speak about."""
        if self.loop is None or self.ws is None:
            return
        message = {"clientContent": {"turns": [{"role": "user", "parts": [{"text": text}]}], "turnComplete": True}}
        asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(message)), self.loop)
