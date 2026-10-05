"""Run by Windows Task Scheduler at a reminder's time: notify, speak, mark as fired.

Usage: pythonw.exe chutku\\remind.py <reminder-id>. The message comes from
data\\reminders.json, never from the command line.
"""
import base64
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chutku.health import TOAST_SHOW, powershell_exe  # noqa: E402  (after the path is set)

_TOAST = r'''
$ErrorActionPreference = 'Stop'
$m = [Console]::In.ReadToEnd() | ConvertFrom-Json
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast scenario="reminder"><visual><binding template="ToastGeneric"><text/><text/></binding></visual><actions><action content="OK" arguments="ok" activationType="system"/></actions></toast>')
$texts = $xml.GetElementsByTagName('text')
$texts.Item(0).AppendChild($xml.CreateTextNode('Chutku reminder')) | Out-Null
$texts.Item(1).AppendChild($xml.CreateTextNode([string]$m.message)) | Out-Null
''' + TOAST_SHOW + r'''
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice.Speak('Reminder. ' + [string]$m.message)
'''


def main():
    from chutku.tools.reminders import _lock, load, save
    if len(sys.argv) != 2 or not sys.argv[1].isalnum():
        return 2
    reminder_id = sys.argv[1]
    entry = load(ROOT).get(reminder_id)
    if not entry or entry.get("fired"):
        return 0
    encoded = base64.b64encode(_TOAST.encode("utf-16-le")).decode("ascii")
    subprocess.run([powershell_exe(), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                   input=json.dumps({"message": entry["message"]}), text=True, encoding="utf-8", timeout=90,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    with _lock:
        data = load(ROOT)
        if reminder_id in data:
            data[reminder_id]["fired"] = True
            save(data, ROOT)
    subprocess.run(["schtasks", "/Delete", "/TN", f"\\Chutku\\Reminder-{reminder_id}", "/F"],
                   capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                   check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
