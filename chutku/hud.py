"""Chutku HUD: a native, frameless, always-on-top panel that appears on Ctrl+Alt+Space or the
wake phrase. Shows a live "reactor" that follows your voice, the transcript, the plan and each
step as it runs, Approve/Deny for steps that need your click, the answer, and a command box.

Safety:
- The window is excluded from screen capture (Gemini never sees it).
- It hides itself while Chutku clicks, so automation cannot press its own Approve button.
- It never takes focus unless you click into the command box.

Layout: drag the top bar to move it; "－"/"＋" or the corner grip resize it (text scales too); clicking any other
app sends it behind that app (Ctrl+Alt+Space brings it back on top). Position and size are remembered.
"""
from __future__ import annotations

import contextlib
import ctypes
import json
import math
from pathlib import Path
import queue
import threading
import time

BG_KEY = "#010203"          # transparent colour key (outside the rounded panel)
PANEL = "#060a12"
GRID = "#0c1524"
TEXT = "#d7e3f4"
DIM = "#5b6b82"
FAINT = "#1b2a40"
ACCENTS = {"listening": "#22d3ee", "thinking": "#a78bfa", "running": "#22d3ee", "confirm": "#fbbf24",
           "done": "#34d399", "error": "#fb7185", "idle": "#22d3ee", "clarify": "#fbbf24"}
LABELS = {"listening": "LISTENING", "thinking": "THINKING", "running": "EXECUTING", "confirm": "NEEDS YOUR OK",
          "done": "DONE", "error": "PROBLEM", "idle": "READY", "clarify": "NEEDS DETAIL"}
STEP_GLYPH = {"COMPLETED": ("✓", "#34d399"), "FAILED": ("✗", "#fb7185"), "DENIED": ("⊘", "#fbbf24"),
              "UNKNOWN": ("?", "#fb7185"), "CANCELLED": ("⊘", "#5b6b82")}
W, H = 460, 640
HIDE_AFTER = 14.0
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.55, 1.3, 0.15
from chutku.core.paths import data_dir as _data_dir
LAYOUT_FILE = _data_dir() / "hud.json"   # W2: never inside the app folder


def _blend(a, b, t):
    a, b = int(a[1:], 16), int(b[1:], 16)
    parts = [round(((a >> s) & 255) * (1 - t) + ((b >> s) & 255) * t) for s in (16, 8, 0)]
    return "#%02x%02x%02x" % tuple(parts)


_instance = None


@contextlib.contextmanager
def hud_hidden():
    """Temporarily hide the HUD (while Chutku captures or clicks the screen)."""
    hud = _instance
    if hud is None or not hud.visible:
        yield
        return
    done = threading.Event()
    hud.commands.put(("withdraw", done))
    done.wait(0.5)
    try:
        yield
    finally:
        hud.commands.put(("restore", None))


class Hud(threading.Thread):
    def __init__(self, status, actions):
        super().__init__(name="chutku-hud", daemon=True)
        self.status = status          # () -> dict (phase, transcript, message, level, session)
        self.actions = actions        # confirm(id, bool), stop(id), submit(text), listen()
        self.commands = queue.Queue()
        self.visible = False
        self.shown_at = 0.0
        self.finished_at = None
        self.frame = 0
        self.ready = threading.Event()
        self.error = None
        self._content_key = None
        self._typing = False
        self._running_row_y = None
        self.flash = None
        self.zoom, self.position = 1.0, None
        self.on_top = True
        self._mouse_down = False
        self._drag = None
        try:
            saved = json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
            self.zoom = min(ZOOM_MAX, max(ZOOM_MIN, float(saved.get("zoom", 1.0))))
            if isinstance(saved.get("position"), list) and len(saved["position"]) == 2:
                self.position = [int(v) for v in saved["position"]]
        except (OSError, ValueError, TypeError):
            pass

    # -- public (any thread) -------------------------------------------------------
    def show(self):
        self.commands.put(("show", None))

    def hide(self):
        self.commands.put(("hide", None))

    # -- Tk thread ---------------------------------------------------------------
    def run(self):
        global _instance
        try:
            user32 = ctypes.windll.user32
            user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # crisp on scaled displays
            import tkinter as tk
            self.tk = tk
            root = self.root = tk.Tk()
            root.withdraw()
            dpi = user32.GetDpiForWindow(root.winfo_id()) or 96
            self.dpi = dpi
            self.s = dpi / 96 * self.zoom
            root.tk.call("tk", "scaling", dpi / 72 * self.zoom)
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-transparentcolor", BG_KEY)
            root.attributes("-alpha", 0.0)
            root.configure(bg=BG_KEY)
            self.w, self.h = int(W * self.s), int(H * self.s)
            self.canvas = tk.Canvas(root, width=self.w, height=self.h, bg=BG_KEY, highlightthickness=0, bd=0)
            self.canvas.pack()
            self.entry = tk.Entry(root, bg="#0a1220", fg=TEXT, insertbackground="#22d3ee", relief="flat",
                                  font=("Cascadia Mono", 10), highlightthickness=1, highlightcolor="#22d3ee",
                                  highlightbackground=FAINT)
            self.entry_window = self.canvas.create_window(self.x(24), self.y(600), window=self.entry, anchor="w",
                                                          width=self.x(360), height=self.y(30))
            self.entry.insert(0, "")
            self.entry.bind("<Return>", self._submit)
            self.entry.bind("<Escape>", lambda _e: self._release_focus())
            self.entry.bind("<Button-1>", lambda _e: self._take_focus())
            self.canvas.bind("<ButtonPress-1>", self._press)
            self.canvas.bind("<B1-Motion>", self._motion)
            self.canvas.bind("<ButtonRelease-1>", self._release)
            root.update_idletasks()
            self.hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
            self._style(no_activate=True)
            import os
            if os.environ.get("CHUTKU_HUD_CAPTURABLE") != "1":  # only visual tests may capture it
                user32.SetWindowDisplayAffinity(self.hwnd, 0x11)  # WDA_EXCLUDEFROMCAPTURE
            _instance = self
            self.ready.set()
            root.after(40, self._tick)
            root.mainloop()
        except Exception as error:  # the HUD is optional; Chutku keeps working without it
            self.error = f"{type(error).__name__}: {error}"
            self.ready.set()

    def x(self, value):
        return value * self.s

    def y(self, value):
        return value * self.s

    def _style(self, *, no_activate):
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(self.hwnd, -20) | 0x80 | 0x8  # tool window, topmost
        style = style | 0x08000000 if no_activate else style & ~0x08000000
        user32.SetWindowLongW(self.hwnd, -20, style)

    def _place(self):
        import ctypes.wintypes as wt
        work = wt.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(work), 0)  # work area (no taskbar)
        screen_w = ctypes.windll.user32.GetSystemMetrics(78) or work.right    # whole virtual desktop
        screen_h = ctypes.windll.user32.GetSystemMetrics(79) or work.bottom
        if self.position and -self.w // 2 < self.position[0] < screen_w - 60 and 0 <= self.position[1] < screen_h - 40:
            left, top = self.position                                       # where the owner last put it
        else:
            left = work.right - self.w - int(self.x(18))
            top = work.bottom - self.h - int(self.y(18))
        self.root.geometry(f"{self.w}x{self.h}+{left}+{top}")

    # -- move, resize, send behind --------------------------------------------------------
    def _save_layout(self):
        try:
            LAYOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            LAYOUT_FILE.write_text(json.dumps({"zoom": round(self.zoom, 2), "position": [self.root.winfo_x(),
                                                                                         self.root.winfo_y()]}),
                                   encoding="utf-8")
        except OSError:
            pass

    def _set_zoom(self, zoom):
        zoom = round(min(ZOOM_MAX, max(ZOOM_MIN, zoom)), 3)
        if abs(zoom - self.zoom) < 0.01:
            return
        left, top = self.root.winfo_x(), self.root.winfo_y()
        self.zoom = zoom
        self.s = self.dpi / 96 * zoom
        self.root.tk.call("tk", "scaling", self.dpi / 72 * zoom)       # fonts follow the size
        self.w, self.h = int(W * self.s), int(H * self.s)
        self.canvas.configure(width=self.w, height=self.h)
        self.entry.configure(font=("Cascadia Mono", 10))
        self.canvas.coords(self.entry_window, self.x(24), self.y(600))
        self.canvas.itemconfigure(self.entry_window, width=self.x(360), height=self.y(30))
        self.root.geometry(f"{self.w}x{self.h}+{left}+{top}")
        self._content_key = None                                      # redraw everything at the new size

    def _press(self, event):
        current = self.canvas.find_withtag("current")
        if current and "button" in self.canvas.gettags(current[0]):
            return                                                    # a button: its own handler runs
        if event.x > self.w - self.x(34) and event.y > self.h - self.y(34):
            self._drag = ("resize", event.x_root, self.zoom)
        elif event.y < self.y(56):
            self._drag = ("move", event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _motion(self, event):
        if not self._drag:
            return
        if self._drag[0] == "move":
            self.root.geometry(f"+{event.x_root - self._drag[1]}+{event.y_root - self._drag[2]}")
        else:
            start_x, start_zoom = self._drag[1], self._drag[2]
            width = W * self.dpi / 96 * start_zoom + (event.x_root - start_x)
            self._set_zoom(width / (W * self.dpi / 96))

    def _release(self, _event):
        if self._drag:
            self._drag = None
            self._save_layout()

    def _raise(self):
        self.on_top = True
        self.root.attributes("-topmost", True)

    def _watch_outside_click(self):
        """A click on any other app sends the HUD behind it (it stays open; Ctrl+Alt+Space raises it again)."""
        user32 = ctypes.windll.user32
        left, right = user32.GetAsyncKeyState(0x01), user32.GetAsyncKeyState(0x02)
        down = bool((left | right) & 0x8000)
        # Bit 0 = pressed since the last check: a quick click between two 40 ms ticks still counts.
        clicked = (down and not self._mouse_down) or bool((left | right) & 0x1)
        if clicked and self.on_top and not self._drag:
            px, py = self.root.winfo_pointerxy()
            left, top = self.root.winfo_rootx(), self.root.winfo_rooty()
            if not (left <= px <= left + self.w and top <= py <= top + self.h):
                self.on_top = False
                self.root.attributes("-topmost", False)
                self._release_focus()
        self._mouse_down = down

    def _take_focus(self):
        self._typing = True
        self._style(no_activate=False)
        self.root.focus_force()
        self.entry.focus_set()

    def _release_focus(self):
        self._typing = False
        self._style(no_activate=True)

    def _submit(self, _event=None):
        text = self.entry.get().strip()
        self.entry.delete(0, "end")
        self._release_focus()
        if text:
            threading.Thread(target=self._safe, args=(self.actions.submit, text), daemon=True).start()

    def _safe(self, function, *args):
        try:
            function(*args)
        except Exception as error:
            self.flash = f"{error}"[:160]

    # -- loop --------------------------------------------------------------------
    def _tick(self):
        try:
            while True:
                command, arg = self.commands.get_nowait()
                if command == "show":
                    if not self.visible:
                        self._place()
                        self.root.deiconify()
                        self.shown_at = time.monotonic()
                    self._raise()                                       # the hotkey always brings it to the front
                    self.visible, self.finished_at = True, None
                elif command == "call":                                 # run on the Tk thread (tests, layout)
                    arg()
                elif command == "hide":
                    self.visible = False
                    self.root.withdraw()
                elif command == "withdraw":
                    if self.visible:
                        self.root.withdraw()
                        self.root.update()
                    if arg is not None:
                        arg.set()
                elif command == "restore":
                    if self.visible:
                        self.root.deiconify()
                        self.root.attributes("-topmost", self.on_top)
        except queue.Empty:
            pass
        if self.visible:
            now = time.monotonic()
            # The animation redraws every frame; the status behind it (a file check, the session) 5 times a second.
            if getattr(self, "_status_at", 0.0) + 0.2 <= now or getattr(self, "_status", None) is None:
                try:
                    self._status = self.status()
                except Exception as error:
                    self._status = {"phase": "error", "message": str(error)}
                self._status_at = now
            state = self._status
            self._draw(state)
            self._fade()
            self._auto_hide(state)
            self._watch_outside_click()
        else:
            self._status = None   # fresh status the moment it shows again
        self.frame += 1
        self.root.after(40 if self.visible else 100, self._tick)   # hidden: only waits for "show"

    def _fade(self):
        alpha = min(1.0, (time.monotonic() - self.shown_at) / 0.18)
        self.root.attributes("-alpha", max(0.05, alpha))

    def _auto_hide(self, state):
        if state.get("phase") in {"done", "error", "clarify"} and not self._typing:
            self.finished_at = self.finished_at or time.monotonic()
            px, py = self.root.winfo_pointerxy()
            inside = self.root.winfo_rootx() <= px <= self.root.winfo_rootx() + self.w and \
                self.root.winfo_rooty() <= py <= self.root.winfo_rooty() + self.h
            if inside:
                self.finished_at = time.monotonic()
            elif time.monotonic() - self.finished_at > HIDE_AFTER:
                self.visible = False
                self.root.withdraw()
        else:
            self.finished_at = None

    # -- drawing -------------------------------------------------------------------
    def _draw(self, state):
        c, s = self.canvas, self.s
        phase = state.get("phase", "idle")
        accent = ACCENTS.get(phase, "#22d3ee")
        session = state.get("session") or {}
        key = (phase, state.get("paused"), state.get("mic_muted"), tuple(state.get("conversation") or ()), state.get("transcript"), state.get("message"), session.get("status"), session.get("reply"),
               tuple((st.get("tool"), st.get("state")) for st in session.get("steps", [])),
               bool(session.get("pending")), len(session.get("queued") or []), self.w)
        if key != self._content_key:
            self._content_key = key
            c.delete("static")
            self._draw_static(state, phase, accent, session)
        c.delete("anim")
        self._draw_reactor(phase, accent, state.get("level", 0.0))
        # scanline + running spinner
        scan = (self.frame * 4) % int(H * s)
        c.create_line(self.x(10), scan, self.w - self.x(10), scan, fill=_blend(PANEL, accent, 0.10), tags="anim")
        c.create_text(self.w - self.x(24), self.y(22), text=time.strftime("%H:%M:%S"), fill=DIM,
                      font=("Cascadia Mono", 8), anchor="e", tags="anim")
        if session.get("status") in {"running", "planning"}:
            spin = "◐◓◑◒"[(self.frame // 3) % 4]
            y = self._running_row_y
            if y:
                c.create_text(self.x(30), y, text=spin, fill=accent, font=("Segoe UI Symbol", 10), tags="anim")
        c.tag_raise("anim")
        c.tag_raise("button")

    def _rounded(self, x0, y0, x1, y1, r, **kw):
        c = self.canvas
        points = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1,
                  x0, y1 - r, x0, y0 + r, x0, y0]
        return c.create_polygon(points, smooth=True, **kw)

    def _draw_static(self, state, phase, accent, session):
        c, x, y = self.canvas, self.x, self.y
        # panel with a soft glow edge
        for i, t in enumerate((0.06, 0.12, 0.25)):
            self._rounded(x(2 - i * 0) + i, y(2) + i, self.w - x(2) - i, self.h - y(2) - i, x(18),
                          fill="" if i < 2 else PANEL, outline=_blend(PANEL, accent, t + 0.1), width=1, tags="static")
        for gx in range(40, W, 28):
            c.create_line(x(gx), y(64), x(gx), y(300), fill=GRID, tags="static")
        for gy in range(64, 300, 28):
            c.create_line(x(14), y(gy), self.w - x(14), y(gy), fill=GRID, tags="static")
        # HUD corner brackets
        for (cx, cy, dx, dy) in ((14, 14, 1, 1), (W - 14, 14, -1, 1), (14, H - 14, 1, -1), (W - 14, H - 14, -1, -1)):
            c.create_line(x(cx), y(cy), x(cx + 16 * dx), y(cy), fill=accent, width=2, tags="static")
            c.create_line(x(cx), y(cy), x(cx), y(cy + 16 * dy), fill=accent, width=2, tags="static")
        c.create_text(x(28), y(22), text="C H U T K U", fill=accent, font=("Bahnschrift", 12, "bold"), anchor="w",
                      tags="static")
        planner = ", ".join(dict.fromkeys(p.get("planner") for p in session.get("planners", []) if p.get("planner")))
        link = ("LIVE · " + str(state["live_model"]).upper()) if state.get("live_model") else             ("NEURAL LINK · " + (planner.upper() if planner else "STANDBY"))
        c.create_text(x(28), y(40), text=link,
                      fill=DIM, font=("Cascadia Mono", 7), anchor="w", tags="static")
        # mic mute toggle (also Ctrl+Alt+M): the room is not heard while Chutku keeps talking
        muted = bool(state.get("mic_muted"))
        mic_button = c.create_text(self.w - x(90), y(40), text="🔇 MUTED" if muted else "🎙 MIC",
                                   fill="#f87171" if muted else DIM, font=("Segoe UI Symbol", 8, "bold"),
                                   anchor="e", tags=("static", "button"))
        c.tag_bind(mic_button, "<Button-1>", lambda _e: self._safe(self.actions.mute))
        # close button
        close = c.create_text(self.w - x(24), y(40), text="✕", fill=DIM, font=("Segoe UI Symbol", 10),
                              anchor="e", tags=("static", "button"))
        c.tag_bind(close, "<Button-1>", lambda _e: self.hide())
        for label, change, right in (("＋", ZOOM_STEP, 46), ("－", -ZOOM_STEP, 66)):
            item = c.create_text(self.w - x(right), y(40), text=label, fill=DIM, font=("Segoe UI Symbol", 10),
                                 anchor="e", tags=("static", "button"))
            c.tag_bind(item, "<Button-1>", lambda _e, d=change: (self._set_zoom(self.zoom + d), self._save_layout()))
        c.create_text(self.w - x(8), self.h - x(8), text="◢", fill=FAINT, font=("Segoe UI Symbol", 9), anchor="se",
                      tags="static")                                  # resize grip
        # status
        c.create_text(self.w / 2, y(268), text="●  " + LABELS.get(phase, phase.upper()), fill=accent,
                      font=("Bahnschrift", 11, "bold"), tags="static")
        top = y(296)
        conversation = state.get("conversation") or []
        if conversation:  # live conversation: the last few lines, newest at the bottom
            for speaker, line in conversation[-5:]:
                mine = speaker == "you"
                label = c.create_text(x(28), top, text=("YOU" if mine else "CHUTKU"), anchor="nw",
                                      fill=DIM if mine else _blend(TEXT, "#22d3ee", 0.5), font=("Cascadia Mono", 7),
                                      tags="static")
                body = c.create_text(x(84), top, text=line.strip()[-260:], anchor="nw", width=x(350),
                                     fill=TEXT if mine else _blend(TEXT, "#22d3ee", 0.25), font=("Segoe UI", 9),
                                     tags="static")
                top = c.bbox(body)[3] + y(6)
            top += y(4)
        transcript = None if conversation else (state.get("transcript") or session.get("goal"))
        if transcript:
            c.create_text(x(28), top, text="›  " + transcript[:220], fill=TEXT, font=("Segoe UI", 10), anchor="nw",
                          width=x(404), tags="static")
            top += y(22) * (1 + len(transcript) // 58)
        message = state.get("message")
        if not transcript and not message and not session and not conversation:
            hints = ("Speak now — I stop when you pause." if phase == "listening" else "Type below or press the mic.",
                     "try:  “spotify kholo”   ·   “what's on my screen?”",
                     "“click the first video”   ·   “build me a snake game”")
            for i, hint in enumerate(hints):
                c.create_text(self.w / 2, top + y(22 + i * 22), text=hint, fill=DIM if i else TEXT,
                              font=("Segoe UI", 9 if i else 10), tags="static")
        if message and not session:
            c.create_text(x(28), top + y(6), text=message[:300], fill=DIM, font=("Segoe UI", 9), anchor="nw",
                          width=x(404), tags="static")
        # steps
        self._running_row_y = None
        steps = session.get("steps", [])[-6:]
        row = top + y(12)
        c.create_line(x(28), row - y(4), self.w - x(28), row - y(4), fill=FAINT, tags="static")
        for step in steps:
            glyph, colour = STEP_GLYPH.get(step.get("state"), ("·", DIM))
            c.create_text(x(30), row + y(10), text=glyph, fill=colour, font=("Segoe UI Symbol", 10), tags="static")
            c.create_text(x(46), row + y(10), text=step.get("tool", ""), fill=DIM, font=("Cascadia Mono", 8),
                          anchor="w", tags="static")
            detail = step.get("purpose") or ""
            c.create_text(x(170), row + y(10), text=detail[:44], fill=TEXT, font=("Segoe UI", 9), anchor="w",
                          tags="static")
            row += y(22)
        if session.get("status") in {"running", "planning"}:
            upcoming = (session.get("queued") or [{}])[0].get("purpose") or "planning the next step…"
            self._running_row_y = row + y(10)
            c.create_text(x(46), row + y(10), text=upcoming[:56], fill=_blend(TEXT, PANEL, 0.3),
                          font=("Segoe UI", 9, "italic"), anchor="w", tags="static")
            row += y(22)
        pending = session.get("pending")
        if pending:
            self._confirm_card(pending, session.get("id"), row + y(10))
        elif session.get("reply") and session.get("status") not in {"running", "planning"}:
            reply, _, tally = session["reply"].partition("[Verified:")
            answer = c.create_text(x(28), row + y(14), text=reply.strip()[:600], fill=TEXT, font=("Segoe UI", 10),
                                   anchor="nw", width=x(404), tags="static")
            if tally:
                bottom = c.bbox(answer)[3] + y(10)
                ok = "Not completed" not in tally
                colour = "#34d399" if ok else "#fbbf24"
                label = c.create_text(x(38), bottom + y(10), text="VERIFIED " + tally.strip(" ]").replace(" steps completed", ""),
                                      fill=colour, font=("Cascadia Mono", 8), anchor="w", width=x(380), tags="static")
                box = c.bbox(label)
                self._rounded(box[0] - x(8), box[1] - y(4), box[2] + x(8), box[3] + y(4), x(6),
                              fill=_blend(PANEL, colour, 0.12), outline=colour, width=1, tags="static")
                c.tag_raise(label)
        if state.get("paused"):  # an emergency stop or unclean restart paused all actions
            amber = "#fbbf24"
            self._rounded(x(24), y(520), self.w - x(24), y(566), x(8), fill="#171204", outline=amber, width=1,
                          tags="static")
            c.create_text(x(38), y(543), text="ACTIONS PAUSED — nothing will run until you resume.", fill=amber,
                          font=("Segoe UI", 9), anchor="w", tags="static")
            resume = c.create_text(self.w - x(38), y(543), text="RESUME ▸", fill=amber,
                                   font=("Bahnschrift", 9, "bold"), anchor="e", tags=("static", "button"))
            c.tag_bind(resume, "<Button-1>", lambda _e: threading.Thread(
                target=self._safe, args=(self.actions.resume,), daemon=True).start())
        # bottom bar
        c.create_line(x(20), y(578), self.w - x(20), y(578), fill=FAINT, tags="static")
        mic = c.create_oval(x(400), y(586), x(428), y(614), outline=accent, width=2, tags=("static", "button"))
        dot = c.create_text(x(414), y(600), text="🎙", fill=accent, font=("Segoe UI Emoji", 10), tags=("static", "button"))
        for item in (mic, dot):
            c.tag_bind(item, "<Button-1>", lambda _e: threading.Thread(target=self._safe, args=(self.actions.listen,),
                                                                       daemon=True).start())
        if session.get("status") in {"running", "planning", "waiting_confirmation"}:
            stop = c.create_text(self.w - x(24), y(268), text="■ STOP", fill="#fb7185", font=("Bahnschrift", 9, "bold"),
                                 anchor="e", tags=("static", "button"))
            c.tag_bind(stop, "<Button-1>", lambda _e: threading.Thread(
                target=self._safe, args=(self.actions.stop, session.get("id")), daemon=True).start())

    def _confirm_card(self, pending, session_id, top):
        c, x, y = self.canvas, self.x, self.y
        amber = "#fbbf24"
        approval = pending.get("approval", {})
        self._rounded(x(24), top, self.w - x(24), top + y(118), x(10), fill="#171204", outline=amber, width=1,
                      tags="static")
        c.create_text(x(38), top + y(16), text="CONFIRM  ·  " + str(approval.get("risk_label") or "").upper(),
                      fill=amber, font=("Bahnschrift", 9, "bold"), anchor="w", tags="static")
        args = approval.get("arguments") or {}
        summary = f"{approval.get('tool', '')}  " + ", ".join(f"{k}={str(v)[:40]}" for k, v in list(args.items())[:3])
        c.create_text(x(38), top + y(36), text=summary[:120], fill=TEXT, font=("Cascadia Mono", 8), anchor="nw",
                      width=x(380), tags="static")
        c.create_text(x(38), top + y(62), text=(approval.get("consequence") or approval.get("reason") or "")[:140],
                      fill=DIM, font=("Segoe UI", 8), anchor="nw", width=x(380), tags="static")
        for label, colour, value, left in (("APPROVE", "#34d399", True, 236), ("DENY", "#fb7185", False, 340)):
            box = self._rounded(x(left), top + y(86), x(left + 90), top + y(110), x(6), fill=_blend(PANEL, colour, 0.18),
                                outline=colour, width=1, tags=("static", "button"))
            text = c.create_text(x(left + 45), top + y(98), text=label, fill=colour, font=("Bahnschrift", 9, "bold"),
                                 tags=("static", "button"))
            for item in (box, text):
                c.tag_bind(item, "<Button-1>", lambda _e, v=value: threading.Thread(
                    target=self._safe, args=(self.actions.confirm, session_id, v), daemon=True).start())

    def _draw_reactor(self, phase, accent, level):
        c, x, y = self.canvas, self.x, self.y
        cx, cy = self.w / 2, y(160)
        t = self.frame / 25.0
        level = max(0.0, min(1.0, level * 12)) if phase == "listening" else 0.0
        breathe = 0.5 + 0.5 * math.sin(t * (4 if phase in {"thinking", "running"} else 1.6))
        # glow core
        core = y(20) + y(22) * level + y(3) * breathe
        for i in range(6, 0, -1):
            r = core + i * y(5)
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline="", fill=_blend(PANEL, accent, 0.05 * (7 - i) * 0.6),
                          tags="anim")
        c.create_oval(cx - core, cy - core, cx + core, cy + core, outline=accent, width=2,
                      fill=_blend(PANEL, accent, 0.35 + 0.25 * breathe), tags="anim")
        # segmented outer ring
        speed = {"thinking": 90, "running": 70, "listening": 40}.get(phase, 18)
        r = y(92)
        for i in range(12):
            start = (i * 30 + t * speed) % 360
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=18, style="arc", outline=accent, width=3,
                         tags="anim")
        r = y(78)
        for i in range(3):
            start = (i * 120 - t * speed * 1.7) % 360
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=70, style="arc",
                         outline=_blend(PANEL, accent, 0.6), width=2, tags="anim")
        r = y(64)
        for i in range(48):
            angle = math.radians(i * 7.5 + t * 10)
            inner = r - (y(6) if i % 4 == 0 else y(3))
            c.create_line(cx + math.cos(angle) * inner, cy + math.sin(angle) * inner, cx + math.cos(angle) * r,
                          cy + math.sin(angle) * r, fill=_blend(PANEL, accent, 0.45), tags="anim")
        if phase == "listening":  # voice bars around the core
            for i in range(32):
                angle = math.radians(i * 11.25)
                wave = 0.3 + 0.7 * abs(math.sin(t * 7 + i * 0.7))
                length = y(4) + y(26) * level * wave
                r0 = core + y(10)
                c.create_line(cx + math.cos(angle) * r0, cy + math.sin(angle) * r0, cx + math.cos(angle) * (r0 + length),
                              cy + math.sin(angle) * (r0 + length), fill=accent, width=2, tags="anim")
