"""The red frame round the laptop screen while the phone controls it (W6 / P5 rule 3): anyone at the laptop sees
that remote control is live. A topmost, click-through Tk window; the phone server starts and ends this process.

    python -m chutku.remote.border
"""
from __future__ import annotations

import tkinter as tk

THICKNESS = 6
COLOR = "#ff2d55"
KEY = "#010203"   # painted transparent


def main():
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    width, height = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{width}x{height}+0+0")
    root.configure(bg=KEY)
    root.attributes("-transparentcolor", KEY)
    canvas = tk.Canvas(root, width=width, height=height, bg=KEY, highlightthickness=0)
    canvas.pack()
    canvas.create_rectangle(THICKNESS // 2, THICKNESS // 2, width - THICKNESS // 2, height - THICKNESS // 2,
                            outline=COLOR, width=THICKNESS)
    canvas.create_text(width // 2, 18, text="📱 Phone se control ho raha hai  ·  Ctrl+Alt+Shift+P to stop",
                       fill=COLOR, font=("Segoe UI", 11, "bold"))
    try:   # let clicks pass through to the windows underneath (WS_EX_TRANSPARENT | WS_EX_LAYERED)
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x20 | 0x80000)
    except Exception:
        pass

    def keep_on_top():
        root.attributes("-topmost", True)
        root.after(2000, keep_on_top)
    keep_on_top()
    root.mainloop()


if __name__ == "__main__":
    main()
