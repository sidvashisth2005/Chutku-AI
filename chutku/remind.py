"""Run by Windows Task Scheduler at a reminder's time: notify, speak, mark as fired.

Usage: pythonw.exe chutku\\remind.py <reminder-id>. The message comes from
data\\reminders.json, never from the command line.
"""
import base64
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the code folder (run as a script by the scheduler)
from chutku.core.paths import home as _home   # noqa: E402
ROOT = _home()   # W2: reminders live in the state root
from chutku.health import TOAST_SHOW, powershell_exe  # noqa: E402  (after the path is set)

_TOAST = r'''
$ErrorActionPreference = 'Stop'
$m = [Console]::In.ReadToEnd() | ConvertFrom-Json
if ($m.toast -eq $false) {   # speak-only call (the neural voice failed): no second notification
  Add-Type -AssemblyName System.Speech
  (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('Reminder. ' + [string]$m.message)
  exit 0
}
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast scenario="reminder"><visual><binding template="ToastGeneric"><text/><text/></binding></visual><actions><action content="OK" arguments="ok" activationType="system"/></actions></toast>')
$texts = $xml.GetElementsByTagName('text')
$texts.Item(0).AppendChild($xml.CreateTextNode('Chutku reminder')) | Out-Null
$texts.Item(1).AppendChild($xml.CreateTextNode([string]$m.message)) | Out-Null
''' + TOAST_SHOW + r'''
if ($m.speak_sapi) {
  Add-Type -AssemblyName System.Speech
  $voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $voice.Speak('Reminder. ' + [string]$m.message)
}
'''


def _neural_voice():
    """Chutku's own voice (Kokoro) unless the owner chose the Windows voice or the model files are missing."""
    try:
        from chutku.core.preferences import Preferences
        from chutku.voice import tts
        return Preferences(ROOT).load().get("voice_engine", "kokoro") == "kokoro" and tts.available()
    except Exception:
        return False


def main():
    from chutku.tools.reminders import _lock, load, save
    if len(sys.argv) != 2 or not sys.argv[1].isalnum():
        return 2
    reminder_id = sys.argv[1]
    entry = load(ROOT).get(reminder_id)
    if not entry or entry.get("fired"):
        return 0
    neural = _neural_voice()
    encoded = base64.b64encode(_TOAST.encode("utf-16-le")).decode("ascii")
    subprocess.run([powershell_exe(), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                   input=json.dumps({"message": entry["message"], "speak_sapi": not neural}), text=True,
                   encoding="utf-8", timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    if neural:
        try:
            from chutku.voice import tts
            tts.speak("Reminder. " + entry["message"])
        except Exception:   # never silent: the Windows voice says it instead
            subprocess.run([powershell_exe(), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                           input=json.dumps({"message": entry["message"], "speak_sapi": True, "toast": False}),
                           text=True, encoding="utf-8", timeout=90,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    with _lock:
        data = load(ROOT)
        if reminder_id in data:
            data[reminder_id]["fired"] = True
            save(data, ROOT)
    from chutku.health import system_exe
    subprocess.run([system_exe("schtasks.exe"), "/Delete", "/TN", f"\\Chutku\\Reminder-{reminder_id}", "/F"],
                   capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                   check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
