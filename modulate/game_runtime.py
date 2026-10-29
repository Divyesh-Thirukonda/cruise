"""Validated game packages and a persistent, isolated QuickJS-NG worker.

Generated JavaScript never runs in this process. The worker exposes no Python
callbacks or I/O APIs, applies engine/OS limits, and is killed on a missed wall
deadline. This is defense in depth, not a VM or a claim of engine exploit safety.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import statistics
import subprocess
import sys
import tempfile
import threading
import time

WIDTH, HEIGHT = 240, 135
MAX_CODE_BYTES = 40 * 1024
MAX_STATE_BYTES = 64 * 1024
MAX_COMMANDS = 128
MAX_PACKAGE_BYTES = 128 * 1024
MAX_MESSAGE_BYTES = 192 * 1024
ENGINE_MEMORY_BYTES = 32 * 1024 * 1024
ENGINE_STACK_BYTES = 256 * 1024
FRAME_CPU_SECONDS = 0.020
STARTUP_CPU_SECONDS = 0.100
FRAME_WALL_SECONDS = 0.350
STARTUP_WALL_SECONDS = 4.0
ENGINE_VERSION = "0.17.0.2"
_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}\Z")
_CONTROLS = {"joystick", "encoder", "button_a", "button_b", "encoder_pressed"}
DEFAULT_INPUT = {"joystick_x": 0.0, "joystick_y": 0.0, "encoder_delta": 0,
                 "button_a": False, "button_b": False, "encoder_pressed": False}


class GameError(ValueError):
    """Invalid package/output or a game worker that cannot continue safely."""


def _json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError) as error:
        raise GameError("Value must be finite JSON") from error


def _keys(value: object, required: set[str], optional: set[str] | None = None) -> dict:
    if type(value) is not dict or not required <= value.keys() or value.keys() - required - (optional or set()):
        raise GameError("Object has missing or unsupported fields")
    return value


def _integer(value: object, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise GameError(f"{name} must be an integer from {low} to {high}")
    return value


def _number(value: object, low: float, high: float, name: str) -> float | int:
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise GameError(f"{name} must be finite and between {low} and {high}")
    return value


def _text(value: object, limit: int, name: str, empty: bool = True) -> str:
    if type(value) is not str or len(value) > limit or (not empty and not value.strip()):
        raise GameError(f"{name} must be a string of at most {limit} characters")
    if any(ord(char) < 32 or ord(char) > 126 for char in value):
        raise GameError(f"{name} must use printable ASCII")
    return value


def _color(value: object, transparent: bool = False) -> str:
    if type(value) is not str or not (_COLOR.fullmatch(value) or (transparent and value == "transparent")):
        raise GameError("Color must be #RRGGBB" + (" or transparent" if transparent else ""))
    return value


def validate_package(package: object) -> dict:
    """Return an independent normalized package; validate assets before spawn."""
    package = _keys(package, {"kind", "title", "code", "assets", "controls"}, {"camera"})
    if package["kind"] != "game":
        raise GameError("Package kind must be game")
    title = _text(package["title"], 80, "title", empty=False)
    code = package["code"]
    if type(code) is not str or not code.strip():
        raise GameError("Game code must be a nonempty JavaScript string")
    try:
        code_size = len(code.encode("utf-8"))
    except UnicodeError as error:
        raise GameError("Game code must be valid UTF-8") from error
    if code_size > MAX_CODE_BYTES:
        raise GameError("Game code exceeds 40 KiB")
    controls = package["controls"]
    if (type(controls) is not list or len(controls) > len(_CONTROLS)
            or any(type(item) is not str or item not in _CONTROLS for item in controls)
            or len(set(controls)) != len(controls)):
        raise GameError("controls must be unique supported control names")
    assets = _keys(package["assets"], {"sprites"})
    sprites = assets["sprites"]
    if type(sprites) is not dict or not 1 <= len(sprites) <= 16:
        raise GameError("Supply 1–16 generated pixel sprites")
    normalized = {}
    pixel_count = 0
    visible = False
    for name, sprite in sprites.items():
        if type(name) is not str or not _ID.fullmatch(name):
            raise GameError("Sprite IDs must be simple names of at most 32 characters")
        sprite = _keys(sprite, {"width", "height", "palette", "pixels"})
        width = _integer(sprite["width"], 1, 32, "sprite width")
        height = _integer(sprite["height"], 1, 32, "sprite height")
        pixel_count += width * height
        if pixel_count > 8192:
            raise GameError("Sprite assets exceed 8192 pixels")
        palette = sprite["palette"]
        if type(palette) is not list or not 1 <= len(palette) <= 16:
            raise GameError("Sprite palettes need 1–16 colors")
        palette = [_color(color, transparent=True) for color in palette]
        pixels = sprite["pixels"]
        if type(pixels) is not list or len(pixels) != height:
            raise GameError("Sprite pixels must contain exactly height rows")
        rows = []
        for row in pixels:
            if type(row) is not list or len(row) != width:
                raise GameError("Sprite pixel rows must match width")
            row = [_integer(index, 0, len(palette) - 1, "palette index") for index in row]
            visible = visible or any(palette[index] != "transparent" for index in row)
            rows.append(row)
        normalized[name] = {"width": width, "height": height, "palette": palette, "pixels": rows}
    if not visible:
        raise GameError("At least one supplied sprite must contain a visible pixel")
    result = {"kind": "game", "title": title, "code": code,
              "assets": {"sprites": normalized}, "controls": list(controls)}
    if "camera" in package:
        camera = _keys(package["camera"], {"target"})
        target = _text(camera["target"], 128, "camera target", empty=False)
        result["camera"] = {"target": target}
    if len(_json(result).encode("utf-8")) > MAX_PACKAGE_BYTES:
        raise GameError("Package exceeds 128 KiB")
    return result


def validate_input(value: object) -> dict:
    value = _keys(value, set(), set(DEFAULT_INPUT))
    result = dict(DEFAULT_INPUT)
    result.update(value)
    for name in ("joystick_x", "joystick_y"):
        _number(result[name], -1, 1, name)
    _integer(result["encoder_delta"], -100, 100, "encoder_delta")
    for name in ("button_a", "button_b", "encoder_pressed"):
        if type(result[name]) is not bool:
            raise GameError(f"{name} must be boolean")
    return result


def validate_state(state: object) -> dict:
    if type(state) is not dict:
        raise GameError("Game state must be a JSON object")
    pending = [(state, 0)]
    count = 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if count > 8192 or depth > 16:
            raise GameError("State is too large or deeply nested")
        if type(value) is dict:
            if len(value) > 256 or any(type(key) is not str or len(key) > 128 for key in value):
                raise GameError("State object has too many or oversized keys")
            pending.extend((item, depth + 1) for item in value.values())
        elif type(value) is list:
            if len(value) > 2048:
                raise GameError("State array exceeds 2048 entries")
            pending.extend((item, depth + 1) for item in value)
        elif type(value) in (int, float):
            _number(value, -1e9, 1e9, "state number")
        elif type(value) is str:
            if len(value) > 4096:
                raise GameError("State string exceeds 4096 characters")
        elif value is not None and type(value) is not bool:
            raise GameError("State contains a non-JSON value")
    if len(_json(state).encode("utf-8")) > MAX_STATE_BYTES:
        raise GameError("State exceeds 64 KiB")
    return state


def validate_commands(commands: object, sprites: dict, allow_camera=False) -> list[dict]:
    if type(commands) is not list or not 1 <= len(commands) <= MAX_COMMANDS:
        raise GameError("draw must return 1–128 commands")
    fields = {"clear": {"op", "color"}, "rect": {"op", "x", "y", "w", "h", "color"},
              "circle": {"op", "x", "y", "r", "color"},
              "line": {"op", "x1", "y1", "x2", "y2", "color"},
              "text": {"op", "x", "y", "text", "color", "size"},
              "sprite": {"op", "id", "x", "y", "scale"},
              "camera": {"op", "x", "y", "w", "h", "mirror", "pixelate", "palette"}}
    cameras = 0
    for command in commands:
        if type(command) is not dict or type(command.get("op")) is not str or command["op"] not in fields:
            raise GameError("Unknown drawing command")
        op = command["op"]
        _keys(command, fields[op])
        if "color" in command:
            _color(command["color"])
        for key in ("x", "y", "x1", "x2", "y1", "y2"):
            if key in command:
                _number(command[key], -1024, 1024, key)
        for key in ("w", "h"):
            if key in command:
                _number(command[key], 0, 1024, key)
        if op == "circle":
            _number(command["r"], 0, 512, "radius")
        elif op == "text":
            _text(command["text"], 80, "draw text")
            _integer(command["size"], 8, 32, "text size")
        elif op == "sprite":
            if type(command["id"]) is not str or command["id"] not in sprites:
                raise GameError("Sprite command references an unknown asset")
            _integer(command["scale"], 1, 8, "sprite scale")
        elif op == "camera":
            cameras += 1
            if not allow_camera or cameras > 1:
                raise GameError("One camera command requires a declared camera source")
            _integer(command["w"], 1, WIDTH, "camera width")
            _integer(command["h"], 1, HEIGHT, "camera height")
            _integer(command["pixelate"], 1, 16, "camera pixelation")
            if type(command["mirror"]) is not bool or command["palette"] not in ("natural", "mono", "neon", "warm"):
                raise GameError("Invalid camera mirror or palette")
    return commands


def validate_frame(frame: object, package: dict) -> dict:
    frame = _keys(frame, {"state", "commands"})
    validate_state(frame["state"])
    validate_commands(frame["commands"], package["assets"]["sprites"], bool(package.get("camera")))
    return frame


class Game:
    """One persistent worker. close() is required; a context manager is supported."""
    def __init__(self, package: object):
        self.package = validate_package(package)
        self._lock = threading.Lock()
        self._process = None
        self._directory = tempfile.TemporaryDirectory(prefix="modulate-game-")
        self._sequence = 0
        worker = str(Path(__file__).with_name("game_worker.py").resolve())
        try:
            self._process = subprocess.Popen(
                [sys.executable, "-I", "-u", worker], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                cwd=self._directory.name, env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
                close_fds=True, start_new_session=True,
            )
            result = self._exchange({"action": "load", "package": self.package}, STARTUP_WALL_SECONDS)
            self.isolation = result["isolation"]
            self.initial_frame = validate_frame(result["frame"], self.package)
        except Exception:
            self.close()
            raise

    def _exchange(self, message: dict, timeout: float) -> dict:
        process = self._process
        if process is None or process.poll() is not None:
            raise GameError("Game worker is closed")
        self._sequence += 1
        message["sequence"] = self._sequence
        request = (_json(message) + "\n").encode("utf-8")
        if len(request) > MAX_MESSAGE_BYTES:
            raise GameError("Worker request is oversized")
        deadline = time.monotonic() + timeout
        received = bytearray()
        position = 0
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdin.fileno(), False)
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE)
            selector.register(process.stdout, selectors.EVENT_READ)
            try:
                while b"\n" not in received:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise GameError("Game worker exceeded its wall-clock deadline")
                    for key, _ in selector.select(remaining):
                        if key.fileobj is process.stdin:
                            try:
                                position += os.write(process.stdin.fileno(), request[position:position + 65536])
                            except BlockingIOError:
                                continue
                            if position == len(request):
                                selector.unregister(process.stdin)
                        else:
                            chunk = os.read(process.stdout.fileno(), 65536)
                            if not chunk:
                                raise GameError("Game worker exited without a result")
                            received.extend(chunk)
                            if len(received) > MAX_MESSAGE_BYTES:
                                raise GameError("Game worker output is oversized")
                raw, _, extra = received.partition(b"\n")
                if extra:
                    raise GameError("Unexpected extra worker output")
                response = json.loads(raw)
                if (type(response) is dict and response.get("sequence") == 0
                        and response.get("ok") is False):
                    raise GameError("Worker startup failed: " + str(response.get("error", "unknown error"))[:600])
                if type(response) is not dict or response.get("sequence") != self._sequence:
                    raise GameError("Worker response sequence mismatch")
                if response.get("ok") is not True:
                    raise GameError(str(response.get("error", "Game execution failed"))[:600])
                return response["result"]
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.close()
                if isinstance(error, GameError):
                    raise
                raise GameError("Invalid game worker response") from error

    def step(self, input: dict | None = None, dt: float = 1 / 30) -> dict:
        controls = validate_input({} if input is None else input)
        _number(dt, 0, 0.1, "dt")
        with self._lock:
            try:
                frame = self._exchange({"action": "step", "input": controls, "dt": dt}, FRAME_WALL_SECONDS)
                return validate_frame(frame, self.package)
            except Exception:
                self.close()
                raise

    def close(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
        if getattr(self, "_directory", None) is not None:
            self._directory.cleanup()

    def __enter__(self) -> "Game":
        return self

    def __exit__(self, *args) -> None:
        self.close()


def verify(package: object) -> dict:
    """Fixed finite checks and separate hostile resource probes, never model tests."""
    checks, errors, metrics = [], [], {}
    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            errors.append(f"{name}: {detail}")
    try:
        normalized = validate_package(package)
        metrics["package_sha256"] = hashlib.sha256(_json(normalized).encode()).hexdigest()
        check("package", True, "Code, generated sprite assets, and controls satisfy bounds")
    except GameError as error:
        check("package", False, str(error))
        return {"passed": False, "checks": checks, "metrics": metrics, "errors": errors}
    times, sprite_seen = [], False
    try:
        with Game(normalized) as game:
            metrics["isolation"] = game.isolation
            check("startup", True, "init and draw returned a valid initial frame")
            frames = [game.initial_frame]
            samples = [{}, {"joystick_x": -1}, {"joystick_x": 1}, {"joystick_y": -1},
                       {"joystick_y": 1}, {"encoder_delta": -1}, {"encoder_delta": 1},
                       {"button_a": True}, {}, {"button_b": True}, {}, {"encoder_pressed": True}]
            for sample in samples:
                for _ in range(4):
                    started = time.monotonic()
                    frames.append(game.step(sample, 1 / 30))
                    times.append((time.monotonic() - started) * 1000)
            sprite_seen = any(command["op"] == "sprite" for frame in frames for command in frame["commands"])
            metrics.update({"frames": len(frames), "max_commands": max(len(frame["commands"]) for frame in frames),
                            "max_state_bytes": max(len(_json(frame["state"]).encode()) for frame in frames),
                            "distinct_states": len({_json(frame["state"]) for frame in frames}),
                            "step_median_ms": round(statistics.median(times), 3),
                            "step_max_ms": round(max(times), 3)})
            check("representative_inputs", True, "48 updates covering joystick, encoder and button inputs")
            check("sprite_output", sprite_seen, "A supplied sprite appears in the sampled draw commands")
    except (GameError, OSError) as error:
        check("execution", False, str(error)[:600])
    probes = {
        "cpu_guard": ("function init(){while(true){}}", ("interrupted", "wall-clock")),
        "memory_guard": ("function init(){return {buffer:new ArrayBuffer(67108864)}}", ("out of memory",)),
        "state_guard": ("function init(){return {items:Array(2048).fill('x'.repeat(80))}}", ("64 KiB",)),
        "command_guard": ("function init(){return {}}; function draw(){return Array(129).fill({op:'clear',color:'#000000'})}", ("command limit",)),
    }
    for name, (code, expected_errors) in probes.items():
        probe = dict(normalized)
        probe["code"] = "function update(s,i,dt){return s}; function draw(){return [{op:'clear',color:'#000000'}]};" + code
        try:
            with Game(probe):
                check(name, False, "Fixed hostile probe was unexpectedly accepted")
        except GameError as error:
            expected = any(marker in str(error) for marker in expected_errors)
            check(name, expected, str(error)[:300])
        except OSError as error:
            check(name, False, str(error))
    return {"passed": not errors, "checks": checks, "metrics": metrics, "errors": errors}
