#!/usr/bin/env python3
"""Build the trusted checkout's native companion; never changes OS permissions."""
import os
import argparse
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", action="store_true", help="Launch the native app at login; preserve its existing pairing")
    parser.add_argument("--skip-build", action="store_true", help="Keep an already built app and its current macOS permission identity")
    args = parser.parse_args()
    if sys.platform != "darwin": raise SystemExit("This installer is for macOS")
    app = Path.home() / "Applications/Modulate.app"
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    python = ROOT / ".venv/bin/python"
    if not python.exists(): raise SystemExit("Install the project's Mac dependencies first")
    binary = contents / "MacOS/Modulate"
    if not args.skip_build:
        subprocess.run(["xcrun", "clang", "-fobjc-arc", "-framework", "Cocoa", "-framework", "ApplicationServices", "-framework", "AVFoundation",
                        str(ROOT / "native/mac-helper/main.m"), "-o", str(binary)], check=True)
    elif not binary.is_file(): raise SystemExit("Build Modulate.app first")
    info = {"CFBundleIdentifier": "com.modulate.companion", "CFBundleName": "Modulate",
            "CFBundleDisplayName": "Modulate", "CFBundleExecutable": "Modulate", "CFBundlePackageType": "APPL",
            "CFBundleVersion": "1", "CFBundleShortVersionString": "0.5.0",
            "NSCameraUsageDescription": "Show your Mac camera live on the paired Modulate display. Frames stay on the local connection.",
            "NSMicrophoneUsageDescription": "Play authorized Mac audio through the paired Modulate speaker.",
            "ModulateRoot": str(ROOT), "ModulatePython": str(python)}
    if not args.skip_build:
        (contents / "Info.plist").write_bytes(plistlib.dumps(info))
        subprocess.run(["codesign", "--force", "--sign", "-", "--identifier", "com.modulate.companion", str(app)], check=True)
    if args.login:
        plist = Path.home() / "Library/LaunchAgents/com.modulate.mac-helper.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)], capture_output=True)
        plist.write_bytes(plistlib.dumps({"Label": "com.modulate.mac-helper", "ProgramArguments": ["/usr/bin/open", "-g", "-a", str(app)],
                                         "RunAtLoad": True, "KeepAlive": False, "LimitLoadToSessionType": "Aqua"}))
        plist.chmod(0o600)
        subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], check=True)
    print(app)

if __name__ == "__main__": main()
