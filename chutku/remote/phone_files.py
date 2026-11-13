"""Laptop files from the phone and phone uploads to ChutkuInbox (PhoneFiles, mixed into remote.server.PhoneHandler)."""
from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from chutku.remote.auth import RemoteDenied
from chutku.remote.streams import _log, file_refusal, MAX_UPLOAD


# Everything Windows runs or installs on a double-click: saved with ".blocked" added, so it is never opened by itself.
BLOCKED_SUFFIXES = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".scr", ".lnk", ".com", ".hta", ".jar",
                    ".msp", ".msix", ".msixbundle", ".appx", ".appxbundle", ".appinstaller", ".application", ".reg",
                    ".msc", ".cpl", ".pif", ".wsf", ".wsh", ".vbe", ".jse", ".psm1", ".psd1", ".ps1xml", ".chm",
                    ".url", ".scf", ".iso", ".img", ".vhd", ".vhdx", ".settingcontent-ms", ".library-ms", ".py",
                    ".pyw", ".dll", ".sys", ".inf", ".gadget", ".xll", ".diagcab"}


def _free_name(path):
    if not path.exists():
        return path
    for number in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise RemoteDenied("Too many files with that name today.", 409)


class PhoneFiles:
    """Methods of PhoneHandler, kept here to keep server.py short."""

    # -- P8: files ---------------------------------------------------------------------------------------------------
    def _upload(self, record):
        self._pin(record, self.headers.get("X-Chutku-PIN") or None)   # inside the PIN session (2026-11-08 review)
        name = Path(str(parse_qs(urlsplit(self.path).query).get("name", ["phone-file"])[0])).name[:120] or "phone-file"
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_UPLOAD:
            raise RemoteDenied("Files up to 200 MB.", 413)
        folder = self.server.inbox / datetime.now().strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        if Path(name).suffix.casefold() in BLOCKED_SUFFIXES:
            name += ".blocked"            # never opened by itself
        target = _free_name(folder / name)
        digest, left = hashlib.sha256(), length
        with open(target, "xb") as stream:     # create-only: never overwrites
            while left:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                stream.write(chunk)
                digest.update(chunk)
                left -= len(chunk)
        if left:
            target.unlink(missing_ok=True)
            raise RemoteDenied("The upload was cut off.", 400)
        _log(self.server.core.base, "file_from_phone", {"path": str(target), "bytes": length,
                                                        "sha256": digest.hexdigest()})
        self._reply(200, {"saved": str(target), "bytes": length, "sha256": digest.hexdigest()})

    # Owner 2026-11-07: browse instead of typing a path. Read-only, inside the PIN session, the same refusals as a fetch.
    def _post_files_places(self, record, data):
        self._pin(record, data.get("pin"))
        from chutku.remote import files_browse
        return files_browse.places()

    def _post_files_list(self, record, data):
        self._pin(record, data.get("pin"))
        from chutku.remote import files_browse
        try:
            return files_browse.listing(data.get("path"), str(data.get("kind") or "all"))
        except PermissionError as error:
            raise RemoteDenied(str(error)) from None

    def _post_files_search(self, record, data):
        self._pin(record, data.get("pin"))
        from chutku.remote import files_browse
        return files_browse.search(data.get("q"), str(data.get("kind") or "all"))

    def _post_files_recent(self, record, data):
        self._pin(record, data.get("pin"))
        from chutku.remote import files_browse
        return files_browse.recent(str(data.get("kind") or "all"))

    def _post_files_get(self, record, data):
        self._pin(record, data.get("pin"))
        path = Path(str(data.get("path") or "")).expanduser()
        reason = file_refusal(path)
        if reason:
            raise RemoteDenied(reason)
        blob = path.read_bytes()
        _log(self.server.core.base, "file_to_phone", {"path": str(path), "bytes": len(blob),
                                                      "sha256": hashlib.sha256(blob).hexdigest()})
        return 200, blob, "application/octet-stream", {"Content-Disposition": f'attachment; filename="{path.name}"'}
