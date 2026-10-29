"""Optional, reversible Mac-output mute for audio already playing on the Pi.

This trusted helper never changes volume or selects an output. CoreAudio writes
address the captured device, not whichever device becomes default during a race.
Device identifiers stay in memory and are omitted from status and errors.
"""
import ctypes
import sys
import threading


class AudioRouteError(Exception):
    pass


class _Address(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32)]


def _address(selector, scope="glob"):
    return _Address(int.from_bytes(selector.encode("ascii"), "big"),
                    int.from_bytes(scope.encode("ascii"), "big"), 0)


class CoreAudioMuteBackend:
    """Fixed public CoreAudio properties from AudioHardware.h/AudioHardwareBase.h.

    get()->{device:(objectID,UID),muted:bool}; set_muted(identity,bool).
    UID is retained only to prevent an object-ID reuse from changing another
    physical output. No generated parameters, arbitrary scripts or volume API.
    """
    def __init__(self):
        self._audio = self._cf = None

    def _load(self):
        if sys.platform != "darwin":
            raise AudioRouteError("Mac output routing is unavailable on this platform")
        if self._audio is not None:
            return
        try:
            audio = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
            cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            address = ctypes.POINTER(_Address)
            audio.AudioObjectGetPropertyData.argtypes = [ctypes.c_uint32, address, ctypes.c_uint32,
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
            audio.AudioObjectGetPropertyData.restype = ctypes.c_int32
            audio.AudioObjectSetPropertyData.argtypes = [ctypes.c_uint32, address, ctypes.c_uint32,
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
            audio.AudioObjectSetPropertyData.restype = ctypes.c_int32
            audio.AudioObjectIsPropertySettable.argtypes = [ctypes.c_uint32, address,
                                                          ctypes.POINTER(ctypes.c_ubyte)]
            audio.AudioObjectIsPropertySettable.restype = ctypes.c_int32
            cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_uint32]
            cf.CFStringGetCString.restype = ctypes.c_bool
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            cf.CFRelease.restype = None
            self._audio, self._cf = audio, cf
        except (OSError, AttributeError):
            raise AudioRouteError("Native Mac output routing is unavailable") from None

    def _read(self, device, selector, value, scope="glob"):
        self._load()
        size = ctypes.c_uint32(ctypes.sizeof(value))
        address = _address(selector, scope)
        if (self._audio.AudioObjectGetPropertyData(device, ctypes.byref(address), 0, None,
                ctypes.byref(size), ctypes.byref(value)) != 0 or size.value != ctypes.sizeof(value)):
            raise AudioRouteError("Could not inspect the selected Mac output")
        return value.value

    def _identity(self, device):
        uid = self._read(device, "uid ", ctypes.c_void_p())
        if not uid:
            raise AudioRouteError("Could not identify the selected Mac output")
        try:
            text = ctypes.create_string_buffer(4096)
            if not self._cf.CFStringGetCString(uid, text, len(text), 0x08000100):
                raise AudioRouteError("Could not identify the selected Mac output")
            return device, text.value.decode("utf-8", errors="strict")
        finally:
            self._cf.CFRelease(uid)

    def get(self):
        device = self._read(1, "dOut", ctypes.c_uint32())
        if not device:
            raise AudioRouteError("No default Mac output is available")
        identity = self._identity(device)
        muted = self._read(device, "mute", ctypes.c_uint32(), "outp")
        if muted not in (0, 1) or self._read(1, "dOut", ctypes.c_uint32()) != device:
            raise AudioRouteError("Mac output changed while inspecting it")
        return {"device": identity, "muted": bool(muted)}

    def set_muted(self, identity, muted):
        if type(muted) is not bool:
            raise AudioRouteError("Mute must be a boolean")
        if self.get()["device"] != identity:
            raise AudioRouteError("Mac output changed; its mute was left alone")
        device = identity[0]
        address = _address("mute", "outp")
        writable = ctypes.c_ubyte()
        if (self._audio.AudioObjectIsPropertySettable(device, ctypes.byref(address), ctypes.byref(writable)) != 0
                or not writable.value):
            raise AudioRouteError("This Mac output does not support native mute")
        value = ctypes.c_uint32(int(muted))
        if self._audio.AudioObjectSetPropertyData(device, ctypes.byref(address), 0, None,
                                                ctypes.sizeof(value), ctypes.byref(value)) != 0:
            raise AudioRouteError("Could not change the selected Mac output mute")


class MacAudioRoute:
    """Call start only after the Pi acknowledges playback; always call stop.

    A pre-existing mute is preserved. A changed device or externally unmuted
    output loses ownership. Failed restoration retains ownership so stop can
    retry. status is cached: it never blocks the device heartbeat on native I/O.
    This in-memory lease cannot recover after a force-killed host process.
    """
    def __init__(self, backend=None):
        self.backend = backend if backend is not None else CoreAudioMuteBackend()
        self._lock = threading.RLock()
        self._device = None
        self._original = None
        self._active = self._owns = False
        self._state = "stopped"
        self._restored = None
        self._error = None

    def status(self):
        with self._lock:
            return {"state": self._state, "active": self._active, "owns_mute": self._owns,
                    "original_muted": self._original, "restored": self._restored, "error": self._error}

    @staticmethod
    def _validate(value):
        if type(value) is not dict or "device" not in value or type(value.get("muted")) is not bool:
            raise AudioRouteError("Native Mac output state is invalid")
        return value

    def start(self):
        with self._lock:
            if self._active:
                return self.status()
            self._error = self._restored = None
            try:
                original = self._validate(self.backend.get())
                self._device, self._original = original["device"], original["muted"]
                self._active = True
                self._owns = not self._original
                if self._owns:
                    # Retain the lease before writing: a failed native call may
                    # still have changed mute, so stop must reconcile its result.
                    self.backend.set_muted(self._device, True)
                current = self._validate(self.backend.get())
                if current["device"] != self._device or current["muted"] is not True:
                    raise AudioRouteError("Mac output changed during routing")
                self._state = "muted" if self._owns else "already_muted"
            except Exception:
                self._state, self._error = "error", "Could not confirm Mac output mute; audio may play on both devices"
            return self.status()

    def _release(self, state, restored):
        self._active = self._owns = False
        self._device = None
        self._state, self._restored = state, restored

    def stop(self):
        with self._lock:
            if not self._active:
                return self.status()
            self._error = None
            if not self._owns:
                self._release("stopped", True)
                return self.status()
            try:
                current = self._validate(self.backend.get())
                if current["device"] != self._device:
                    self._release("output_changed", False)
                    return self.status()
                if current["muted"] is not True:
                    self._release("mute_changed", current["muted"] == self._original)
                    return self.status()
                self.backend.set_muted(self._device, self._original)
                restored = self._validate(self.backend.get())
                if restored["device"] != self._device or restored["muted"] != self._original:
                    raise AudioRouteError("Could not confirm Mac output restoration")
                self._release("stopped", True)
            except Exception:
                self._state, self._error = "error", "Could not restore Mac mute; check the Mac output setting"
            return self.status()
