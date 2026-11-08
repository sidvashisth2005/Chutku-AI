"""Updates for installed copies (owner 2026-11-08: "publish an update to existing users, like a pop up").

The public releases repository holds one file per release, Chutku-Setup-for-Windows.exe, with the app inside. The
dashboard asks GitHub for the newest release (at most every 6 hours), and the page shows a popup when it is newer
than this copy. "Update now" downloads the setup (checked against GitHub's SHA-256 digest and size), runs it silently
(`/SILENT /RELAUNCH=yes`: it stops Chutku, replaces the app folder, keeps the user's data and starts Chutku again).
The owner's git checkout never updates itself this way: it is a developer copy (git pull).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import urllib.request

from chutku.core.paths import CODE_ROOT, is_checkout

LATEST = "https://api.github.com/repos/sidvashisth2005/Chutku-releases/releases/latest"
DOWNLOADS = "https://github.com/sidvashisth2005/Chutku-releases/releases/download/"
SETUP_NAME = "Chutku-Setup-for-Windows.exe"
CHECK_EVERY = 6 * 3600
_LOCK = threading.Lock()
_STATE = {"checked": 0.0, "release": None, "job": {"state": "idle"}}


def current_version():
    """This copy's version: version.json in an installed app, pyproject.toml in a checkout."""
    try:
        return json.loads((CODE_ROOT / "version.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (CODE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return match.group(1) if match else "0.0.0"
    except OSError:
        return "0.0.0"


def _parts(version):
    return tuple(int(n) for n in re.findall(r"\d+", str(version))[:3]) or (0,)


def newer(latest, current):
    return _parts(latest) > _parts(current)


def _fetch_json(url, timeout=15):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Chutku"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _release(data):
    """The parts of GitHub's release JSON the popup needs; None when it holds no setup file of ours."""
    asset = next((a for a in data.get("assets") or [] if a.get("name") == SETUP_NAME), None)
    if not asset or not str(asset.get("browser_download_url", "")).startswith(DOWNLOADS):
        return None
    digest = str(asset.get("digest") or "")
    return {"version": str(data.get("tag_name", "")).removeprefix("v"), "notes": str(data.get("body") or "")[:2000],
            "url": asset["browser_download_url"], "size": int(asset.get("size") or 0),
            "sha256": digest.removeprefix("sha256:").lower() if digest.startswith("sha256:") else None}


def check(*, fetch=_fetch_json, clock=time.time, force=False):
    """What the popup shows. Never raises: no internet simply means no popup."""
    with _LOCK:
        if force or clock() - _STATE["checked"] > CHECK_EVERY:
            try:
                _STATE["release"] = _release(fetch(LATEST))
            except Exception:   # offline, GitHub busy, rate-limited: try again at the next check
                _STATE["release"] = None
            _STATE["checked"] = clock()
        release, job = _STATE["release"], dict(_STATE["job"])
    current = current_version()
    available = bool(release and newer(release["version"], current))
    return {"current": current, "latest": release["version"] if release else None, "available": available,
            "notes": release["notes"] if available else "", "size": release["size"] if available else 0,
            "developer_copy": is_checkout(), "job": job}


def _download(url, target, size, sha256, progress):
    digest = hashlib.sha256()
    done = 0
    request = urllib.request.Request(url, headers={"User-Agent": "Chutku"})
    with urllib.request.urlopen(request, timeout=60) as response, open(target, "wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            progress(done)
    if (size and done != size) or (sha256 and digest.hexdigest() != sha256):
        Path(target).unlink(missing_ok=True)
        raise OSError("The downloaded update did not match its checksum and was deleted. Try again later.")


def _launch(setup):
    subprocess.Popen([str(setup), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=yes"],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


def install(*, download=_download, launch=_launch, folder=None):
    """Start the update in the background; the page polls check()["job"]."""
    if is_checkout():
        raise ValueError("This is a developer copy: update it with git pull.")
    with _LOCK:
        release = _STATE["release"]
        if not release or not newer(release["version"], current_version()):
            raise ValueError("No newer version to install.")
        if _STATE["job"]["state"] in ("downloading", "installing"):
            return dict(_STATE["job"])
        _STATE["job"] = {"state": "downloading", "done": 0, "size": release["size"], "version": release["version"]}

    def run():
        target = Path(folder or tempfile.gettempdir()) / SETUP_NAME
        try:
            download(release["url"], target, release["size"], release["sha256"],
                     lambda done: _STATE["job"].update(done=done))
            _STATE["job"].update(state="installing")
            launch(target)   # the setup stops Chutku, installs, and starts the new version
        except Exception as error:
            _STATE["job"] = {"state": "failed", "error": str(error)[:300] or "The update could not be downloaded."}
    threading.Thread(target=run, name="chutku-update", daemon=True).start()
    return dict(_STATE["job"])


def reset_for_tests():
    with _LOCK:
        _STATE.update(checked=0.0, release=None, job={"state": "idle"})
