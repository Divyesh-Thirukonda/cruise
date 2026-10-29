"""Small native brightness helper, isolated from the model and bounded by its caller.

DisplayServices is a private macOS API: unsupported displays report an error.
API references: https://github.com/nriley/brightness/blob/master/brightness.c
https://chromium.googlesource.com/chromium/src/tools/+/b3e062b188e2c0bf368503aa8d4f5830a52f857c/mac/power/driver.py
The bridge uses only fixed get/set operations, never generated script text.
"""
import ctypes
import json
import math
import sys


def brightness(action, value=None):
    if sys.platform != "darwin" or action not in {"get", "set"}:
        raise ValueError("Native brightness is unavailable")
    if action == "set" and (type(value) is not int or not 0 <= value <= 100):
        raise ValueError("Brightness must be an integer from 0 to 100")
    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    cg.CGMainDisplayID.restype = ctypes.c_uint32
    display = cg.CGMainDisplayID()
    library = ctypes.CDLL("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices")
    library.DisplayServicesGetBrightness.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_float)]
    library.DisplayServicesGetBrightness.restype = ctypes.c_int
    if action == "set":
        library.DisplayServicesSetBrightness.argtypes = [ctypes.c_uint32, ctypes.c_float]
        library.DisplayServicesSetBrightness.restype = ctypes.c_int
        if library.DisplayServicesSetBrightness(display, value / 100) != 0:
            raise ValueError("Display brightness cannot be set")
    result = ctypes.c_float()
    if library.DisplayServicesGetBrightness(display, ctypes.byref(result)) != 0 or not math.isfinite(result.value):
        raise ValueError("Display brightness cannot be read")
    return {"brightness": max(0, min(100, round(result.value * 100)))}


if __name__ == "__main__":
    try:
        result = brightness(sys.argv[1], int(sys.argv[2]) if len(sys.argv) == 3 else None)
        print(json.dumps(result))
    except Exception:
        print('{"error":"Native brightness is unavailable for this display"}')
        sys.exit(1)
