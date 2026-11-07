"""Live check of the phone remote's smart tap and magnetic pointer lookups (chutku/remote/targets.py) on real Windows
controls. Opens a small always-on-top WinForms window (a button and a text box) for a few seconds, taps near them
through the real UI Automation code, and closes it. Nothing is clicked.

    .venv\\Scripts\\python.exe scripts\\verify_smart_tap.py
"""
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chutku.remote import targets  # noqa: E402
from chutku.remote.control import primary_monitor  # noqa: E402

FORM = r"""
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object Windows.Forms.Form; $f.Text = 'Chutku snap test'; $f.TopMost = $true; $f.Width = 420; $f.Height = 220
$f.StartPosition = 'Manual'; $f.Left = 200; $f.Top = 200
$b = New-Object Windows.Forms.Button; $b.Text = 'Snap OK'; $b.Left = 20; $b.Top = 20; $b.Width = 90; $b.Height = 30
$t = New-Object Windows.Forms.TextBox; $t.Name = 'field'; $t.Left = 20; $t.Top = 90; $t.Width = 220
$f.Controls.Add($b); $f.Controls.Add($t)
$timer = New-Object Windows.Forms.Timer; $timer.Interval = 15000; $timer.Add_Tick({ $f.Close() }); $timer.Start()
[void]$f.ShowDialog()
"""


def rect_of(name):
    def job():
        u = targets._uia()
        root = u.ua.GetRootElement()
        window = root.FindFirst(2, u.ua.CreatePropertyCondition(30005, "Chutku snap test"))   # children, Name
        if not window:
            return None
        found = window.FindFirst(4, u.ua.CreatePropertyCondition(30005, name))               # descendants
        if not found:
            return None
        r = found.CurrentBoundingRectangle
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    return targets._run(job, 5)


def main():
    form = subprocess.Popen(["powershell", "-NoProfile", "-Command", FORM], creationflags=0x08000000)
    try:
        button = None
        for _ in range(60):
            time.sleep(0.25)
            button = rect_of("Snap OK")
            if button:
                break
        if not button:
            print("FAIL: the test window did not appear")
            return 1
        field = rect_of("")
        monitor = primary_monitor()
        bx, by, bw, bh = button
        checks = []
        start = time.perf_counter()
        near = targets.snap(bx + bw + 12, by + bh // 2, 25, monitor)       # 12 px right of the button
        took = (time.perf_counter() - start) * 1000
        checks.append(("a tap 12 px off the button lands on its middle",
                       near and near[2]["kind"] == "button" and near[:2] == (bx + bw // 2, by + bh // 2), near, took))
        on = targets.snap(bx + 5, by + 5, 25, monitor)
        checks.append(("a tap on the button stays exactly where it was", on and on[:2] == (bx + 5, by + 5), on, None))
        far = targets.snap(bx + bw + 70, by + bh // 2, 25, monitor)
        checks.append(("a tap 70 px away (radius 25) is not moved", far is None, far, None))
        if field:
            fx, fy, fw, fh = field
            below = targets.snap(fx + 40, fy + fh + 8, 25, monitor)
            checks.append(("a tap just below the text box lands inside it, under the finger",
                           below and below[2]["kind"] == "field" and below[0] == fx + 40 and fy <= below[1] < fy + fh,
                           below, None))
        hovered = targets.hover(bx + 3, by + 3, monitor)
        checks.append(("hover over the button finds it", hovered and hovered["kind"] == "button", hovered, None))
        failed = 0
        for name, ok, got, ms in checks:
            failed += not ok
            print(("PASS" if ok else "FAIL"), name, "->", got, f"({ms:.0f} ms)" if ms else "")
        return 1 if failed else 0
    finally:
        form.kill()


if __name__ == "__main__":
    sys.exit(main())
