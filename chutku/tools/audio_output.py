"""List playback devices and switch the default one ("switch audio to headphones").

Uses the Windows Core Audio COM interfaces through ctypes (no extra packages). Switching uses
IPolicyConfig, the interface Windows' own Sound settings use; it is undocumented but stable
since Windows 7. The change is read back, and the previous device is returned for undo.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import uuid

from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification

_CLSID_ENUMERATOR = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_ENUMERATOR = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_CLSID_POLICY = "{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}"
_IID_POLICY = "{F8679F50-850A-41CF-9C72-430F290290C8}"
_FRIENDLY_NAME = ("{A45C254E-DF1C-4EFD-8020-67D146A850E0}", 14)
_RENDER, _ACTIVE, _ROLES = 0, 1, (0, 1, 2)  # eRender, DEVICE_STATE_ACTIVE, console/multimedia/communications


class _GUID(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_byte * 16)]

    @classmethod
    def of(cls, text):
        guid = cls()
        ctypes.memmove(guid.bytes, uuid.UUID(text).bytes_le, 16)
        return guid


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", w.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("value", ctypes.c_void_p), ("pad", ctypes.c_void_p)]


def _method(pointer, index, restype, *argtypes):
    vtable = ctypes.cast(ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])


def _check(hresult, what):
    if hresult not in (0, 1):  # S_OK, or S_FALSE ("already that value")
        raise OSError(f"{what} failed (0x{hresult & 0xFFFFFFFF:08X}).")


def _release(pointer):
    if pointer:
        _method(pointer, 2, ctypes.c_ulong)(pointer)


class _Com:
    def __enter__(self):
        self.ole = ctypes.OleDLL("ole32")
        hresult = ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # apartment-threaded
        self.owned = hresult in (0, 1)
        return self

    def __exit__(self, *_):
        if self.owned:
            ctypes.windll.ole32.CoUninitialize()

    def create(self, clsid, iid):
        pointer = ctypes.c_void_p()
        _check(ctypes.windll.ole32.CoCreateInstance(ctypes.byref(_GUID.of(clsid)), None, 1,  # CLSCTX_INPROC_SERVER
                                                    ctypes.byref(_GUID.of(iid)), ctypes.byref(pointer)),
               "Opening Windows audio")
        return pointer


def _device_name(device):
    store = ctypes.c_void_p()
    _check(_method(device, 4, ctypes.c_long, w.DWORD, ctypes.POINTER(ctypes.c_void_p))(
        device, 0, ctypes.byref(store)), "Reading a device")  # STGM_READ
    try:
        key = _PROPERTYKEY(_GUID.of(_FRIENDLY_NAME[0]), _FRIENDLY_NAME[1])
        value = _PROPVARIANT()
        _check(_method(store, 5, ctypes.c_long, ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT))(
            store, ctypes.byref(key), ctypes.byref(value)), "Reading a device name")
        try:
            return ctypes.wstring_at(value.value) if value.vt == 31 and value.value else "Unknown device"
        finally:
            ctypes.windll.ole32.PropVariantClear(ctypes.byref(value))
    finally:
        _release(store)


def _device_id(device):
    text = ctypes.c_wchar_p()
    _check(_method(device, 5, ctypes.c_long, ctypes.POINTER(ctypes.c_wchar_p))(device, ctypes.byref(text)),
           "Reading a device id")
    try:
        return text.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(text)


def outputs():
    """Active playback devices: [{"name", "id", "default"}]."""
    with _Com() as com:
        enumerator = com.create(_CLSID_ENUMERATOR, _IID_ENUMERATOR)
        try:
            default = ctypes.c_void_p()
            default_id = None
            if _method(enumerator, 4, ctypes.c_long, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
                    enumerator, _RENDER, 1, ctypes.byref(default)) == 0:  # multimedia role
                default_id = _device_id(default)
                _release(default)
            collection = ctypes.c_void_p()
            _check(_method(enumerator, 3, ctypes.c_long, ctypes.c_int, w.DWORD, ctypes.POINTER(ctypes.c_void_p))(
                enumerator, _RENDER, _ACTIVE, ctypes.byref(collection)), "Listing playback devices")
            try:
                count = w.UINT()
                _check(_method(collection, 3, ctypes.c_long, ctypes.POINTER(w.UINT))(collection, ctypes.byref(count)),
                       "Counting devices")
                devices = []
                for index in range(min(count.value, 32)):
                    device = ctypes.c_void_p()
                    _check(_method(collection, 4, ctypes.c_long, w.UINT, ctypes.POINTER(ctypes.c_void_p))(
                        collection, index, ctypes.byref(device)), "Opening a device")
                    try:
                        device_id = _device_id(device)
                        devices.append({"name": _device_name(device), "id": device_id,
                                        "default": device_id == default_id})
                    finally:
                        _release(device)
                return devices
            finally:
                _release(collection)
        finally:
            _release(enumerator)


def set_default(device_id):
    with _Com() as com:
        policy = com.create(_CLSID_POLICY, _IID_POLICY)
        try:
            set_endpoint = _method(policy, 13, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int)
            for role in _ROLES:
                _check(set_endpoint(policy, device_id, role), "Switching the playback device")
        finally:
            _release(policy)


_IID_ENDPOINT_VOLUME = "{5CDF2C82-841E-4546-9722-0CF74078229A}"


def master_volume(level=None, muted=None):
    """Read (and optionally set) the default playback device's volume: {"level": 0-100, "muted": bool}.

    Direct Core Audio calls (IMMDevice::Activate -> IAudioEndpointVolume), so no PowerShell or C# compile.
    """
    with _Com() as com:
        enumerator = com.create(_CLSID_ENUMERATOR, _IID_ENUMERATOR)
        device = endpoint = ctypes.c_void_p()
        try:
            device = ctypes.c_void_p()
            _check(_method(enumerator, 4, ctypes.c_long, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
                enumerator, _RENDER, 1, ctypes.byref(device)), "Finding the playback device")  # multimedia role
            endpoint = ctypes.c_void_p()
            _check(_method(device, 3, ctypes.c_long, ctypes.POINTER(_GUID), w.DWORD, ctypes.c_void_p,
                           ctypes.POINTER(ctypes.c_void_p))(
                device, ctypes.byref(_GUID.of(_IID_ENDPOINT_VOLUME)), 23, None, ctypes.byref(endpoint)),
                "Opening the volume control")  # CLSCTX_ALL
            if level is not None:
                _check(_method(endpoint, 7, ctypes.c_long, ctypes.c_float, ctypes.c_void_p)(
                    endpoint, level / 100.0, None), "Setting the volume")
            if muted is not None:
                _check(_method(endpoint, 14, ctypes.c_long, w.BOOL, ctypes.c_void_p)(
                    endpoint, bool(muted), None), "Setting mute")
            scalar, mute = ctypes.c_float(), w.BOOL()
            _check(_method(endpoint, 9, ctypes.c_long, ctypes.POINTER(ctypes.c_float))(endpoint, ctypes.byref(scalar)),
                   "Reading the volume")
            _check(_method(endpoint, 15, ctypes.c_long, ctypes.POINTER(w.BOOL))(endpoint, ctypes.byref(mute)),
                   "Reading mute")
            return {"level": int(round(scalar.value * 100)), "muted": bool(mute.value)}
        finally:
            _release(endpoint)
            _release(device)
            _release(enumerator)


def match(devices, wanted):
    """The one device whose name contains every word of ``wanted`` (case-insensitive)."""
    words = [word for word in wanted.casefold().replace("-", " ").split() if word not in {"the", "my", "to"}]
    aliases = {"headphones": ("headphone", "headset", "earphone", "buds", "airpods"),
               "headphone": ("headphone", "headset", "earphone", "buds", "airpods"),
               "speakers": ("speaker",), "speaker": ("speaker",), "tv": ("tv", "hdmi", "display")}
    found = []
    for device in devices:
        name = device["name"].casefold()
        if words and all(any(alias in name for alias in aliases.get(word, (word,))) for word in words):
            found.append(device)
    if len(found) != 1:
        names = ", ".join(d["name"] for d in devices) or "none"
        raise ValueError(("Several devices match" if found else "No playback device matches")
                         + f" “{wanted}”. Available: {names}.")
    return found[0]


def _list(arguments, context):
    try:
        devices = outputs()
    except OSError as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    return ToolResult({"devices": [{"name": d["name"], "default": d["default"]} for d in devices]},
                      Verification.PASS if devices else Verification.FAIL)


def _validate_set(arguments):
    if set(arguments) != {"device"} or not isinstance(arguments["device"], str) or not 1 <= len(arguments["device"]) <= 80:
        raise ValueError("Name the playback device, e.g. headphones or speakers.")


def _set(arguments, context):
    try:
        devices = outputs()
        target = match(devices, arguments["device"])
        previous = next((d["name"] for d in devices if d["default"]), None)
        if not target["default"]:
            set_default(target["id"])
        now = next((d for d in outputs() if d["default"]), None)
    except (OSError, ValueError) as error:
        return ToolResult({"error": str(error)}, Verification.FAIL)
    ok = now is not None and now["id"] == target["id"]
    return ToolResult({"device": target["name"], "previous": previous, "switched": ok},
                      Verification.PASS if ok else Verification.FAIL)


def register_audio_output_tools(registry):
    registry.register(Tool("audio.outputs", "List the PC's playback devices (speakers, headphones, HDMI) and which one "
        "is in use.", Risk.OBSERVATION, _list, _no_arguments, required_capability="audio.observe",
        argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="not_applicable", success_predicate="devices_listed"))
    registry.register(Tool("audio.set_output", "Switch sound to another playback device by name (e.g. headphones, "
        "speakers, TV). Reads the change back; the previous device is returned so it can be switched back.",
        Risk.REVERSIBLE, _set, _validate_set, required_capability="audio.modify",
        argument_schema={"type": "object", "properties": {"device": {"type": "string", "minLength": 1, "maxLength": 80}},
                         "required": ["device"], "additionalProperties": False},
        reversibility="compensatable", success_predicate="default_playback_device_read_back"))


def _no_arguments(arguments):
    if arguments != {}:
        raise ValueError("This takes no arguments.")
