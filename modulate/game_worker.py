"""Private worker entrypoint. Run only through game_runtime.Game.

Requires quickjs-ng==0.17.0.2, imported as quickjs. No host callbacks are added.
Native engine defects remain a residual risk; OS fences are defense in depth.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import socket
import sys

# -I excludes the working directory; insert only our fixed, trusted package root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modulate.game_runtime import (ENGINE_MEMORY_BYTES, ENGINE_STACK_BYTES, ENGINE_VERSION,
    FRAME_CPU_SECONDS, STARTUP_CPU_SECONDS, MAX_MESSAGE_BYTES, GameError,
    _json, validate_package, validate_frame, validate_input, _number)


def _os_fence() -> str:
    if sys.platform == "darwin":
        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        sandbox = library.sandbox_init
        sandbox.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)]
        sandbox.restype = ctypes.c_int
        error = ctypes.c_char_p()
        profile = (b"(version 1)(allow default)(deny network*)(deny file-read*)(deny file-write*)"
                   b"(deny process-fork)(deny process-exec)")
        if sandbox(profile, 0, ctypes.byref(error)) != 0:
            raise GameError("macOS sandbox could not be installed")
        return "macOS sandbox: file/network access and child execution denied"
    if sys.platform.startswith("linux"):
        path = ctypes.util.find_library("seccomp")
        if not path:
            raise GameError("Linux worker requires libseccomp (Debian package libseccomp2)")
        library = ctypes.CDLL(path, use_errno=True)
        library.seccomp_init.argtypes = [ctypes.c_uint32]
        library.seccomp_init.restype = ctypes.c_void_p
        library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
        library.seccomp_syscall_resolve_name.restype = ctypes.c_int
        library.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
        library.seccomp_rule_add.restype = ctypes.c_int
        library.seccomp_load.argtypes = [ctypes.c_void_p]
        library.seccomp_load.restype = ctypes.c_int
        library.seccomp_release.argtypes = [ctypes.c_void_p]
        context = library.seccomp_init(0x7FFF0000)  # default ALLOW; explicit syscall denials below
        if not context:
            raise GameError("Could not create seccomp filter")
        denied = ("open openat openat2 creat socket socketpair connect bind listen accept accept4 "
                  "sendto sendmsg sendmmsg recvfrom recvmsg recvmmsg execve execveat fork vfork clone clone3 "
                  "ptrace process_vm_readv process_vm_writev kill tkill tgkill mount umount2 pivot_root "
                  "unshare setns bpf perf_event_open io_uring_setup io_uring_enter io_uring_register "
                  "memfd_create open_by_handle_at name_to_handle_at link linkat symlink symlinkat "
                  "unlink unlinkat rename renameat renameat2 mkdir mkdirat rmdir truncate "
                  "chmod fchmod fchmodat chown fchown fchownat mknod mknodat").split()
        try:
            for name in denied:
                syscall = library.seccomp_syscall_resolve_name(name.encode())
                if syscall >= 0 and library.seccomp_rule_add(context, 0x00050000 | errno.EPERM, syscall, 0) != 0:
                    raise GameError("Could not install seccomp syscall rule")
            if library.seccomp_load(context) != 0:
                raise GameError("Could not activate seccomp filter")
        finally:
            library.seccomp_release(context)
        return "Linux seccomp: file-open/network/process creation syscalls denied"
    raise GameError("Game worker requires Linux or macOS OS isolation")


def _limits() -> dict:
    limits = {}
    for name, amount in (("RLIMIT_CORE", 0), ("RLIMIT_FSIZE", 0), ("RLIMIT_NOFILE", 32), ("RLIMIT_CPU", 300)):
        identifier = getattr(resource, name, None)
        if identifier is not None:
            _, maximum = resource.getrlimit(identifier)
            cap = amount if maximum == resource.RLIM_INFINITY else min(amount, maximum)
            resource.setrlimit(identifier, (cap, cap))
            limits[name] = cap
    if sys.platform.startswith("linux"):
        cap = 256 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        limits["RLIMIT_AS"] = cap
    return limits


def _check_os_fence() -> dict:
    """Fail closed unless fixed filesystem/network attempts are denied by the OS."""
    def must_deny(operation):
        try:
            result = operation()
        except OSError as error:
            if error.errno in (errno.EPERM, errno.EACCES):
                return True
            raise GameError("OS isolation probe failed without a permission denial") from error
        if hasattr(result, "close"):
            result.close()
        raise GameError("OS isolation probe unexpectedly succeeded")
    def connect():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.1)
            connection.connect(("127.0.0.1", 9))
    return {"file_read_denied": must_deny(lambda: open("/etc/hosts", "rb")),
            "file_write_denied": must_deny(lambda: open("modulate-os-fence-probe", "wb")),
            "network_denied": must_deny(connect)}


# This closure is created before generated code. New Function gives the game its
# own global scope, with no access to the private harness closure or Python.
_HARNESS = r"""
(() => {
  const makeFunction = Function;
  const parse = JSON.parse.bind(JSON), stringify = JSON.stringify.bind(JSON);
  const isArray = Array.isArray, keys = Object.keys, prototype = Object.getPrototypeOf;
  const objectPrototype = Object.prototype, finite = Number.isFinite;
  let game, state;
  function checkJSON(value, depth, budget) {
    if (++budget.count > 8192 || depth > 16) throw Error('JSON structure limit');
    if (value === null || typeof value === 'boolean') return;
    if (typeof value === 'number') {
      if (!finite(value) || value < -1e9 || value > 1e9) throw Error('Nonfinite or oversized number');
      return;
    }
    if (typeof value === 'string') {
      if (value.length > 4096) throw Error('JSON string limit');
      return;
    }
    if (typeof value !== 'object') throw Error('State/output must contain only JSON values');
    if (isArray(value)) {
      if (value.length > 2048) throw Error('JSON array limit');
      for (let i = 0; i < value.length; i++) checkJSON(value[i], depth+1, budget);
    } else {
      const p = prototype(value);
      if (p !== objectPrototype && p !== null) throw Error('State/output must use plain objects');
      const names = keys(value);
      if (names.length > 256) throw Error('JSON object limit');
      for (const name of names) {
        if (name.length > 128) throw Error('JSON key limit');
        checkJSON(value[name], depth+1, budget);
      }
    }
  }
  function cloneState(value) {
    if (!value || isArray(value) || typeof value !== 'object') throw Error('State must be an object');
    checkJSON(value, 0, {count:0});
    const encoded = stringify(value);
    if (typeof encoded !== 'string' || encoded.length > 65536) throw Error('State exceeds 64 KiB');
    return parse(encoded);
  }
  function frame() {
    const commands = game.draw(cloneState(state));
    if (!isArray(commands) || commands.length < 1 || commands.length > 128) throw Error('Drawing command limit');
    checkJSON(commands, 0, {count:0});
    const result = stringify({state,commands});
    if (typeof result !== 'string' || result.length > 160000) throw Error('Frame output limit');
    return result;
  }
  return function(action, payload, dt) {
    if (action === 'load') {
      game = makeFunction('"use strict";\n' + payload + '\n;return {init,update,draw};')();
      if (!game || typeof game.init !== 'function' || typeof game.update !== 'function' || typeof game.draw !== 'function')
        throw Error('Define synchronous init, update, and draw functions');
      state = cloneState(game.init());
    } else {
      state = cloneState(game.update(cloneState(state), parse(payload), dt));
    }
    return frame();
  };
})()
"""


def main() -> int:
    sequence = 0
    try:
        import quickjs
        version = importlib.metadata.version("quickjs-ng")
        if version != ENGINE_VERSION:
            raise GameError(f"Install quickjs-ng=={ENGINE_VERSION}; found {version}")
        context = quickjs.Context()
        context.set_memory_limit(ENGINE_MEMORY_BYTES)
        context.set_max_stack_size(ENGINE_STACK_BYTES)
        context.set_time_limit(STARTUP_CPU_SECONDS)
        dispatch = context.eval(_HARNESS)
        host_api_absent = context.eval("[typeof process,typeof require,typeof std,typeof os,typeof fetch,typeof XMLHttpRequest,typeof WebSocket].every(x=>x==='undefined')")
        if not host_api_absent:
            raise GameError("Unexpected JavaScript host APIs")
        limits = _limits()
        isolation = {"engine": "quickjs-ng", "version": version, "os_fence": _os_fence(),
                     "engine_memory_bytes": ENGINE_MEMORY_BYTES, "stack_bytes": ENGINE_STACK_BYTES,
                     "frame_cpu_seconds": FRAME_CPU_SECONDS, "resource_limits": limits,
                     "host_callbacks": False, "module_loader": False}
        isolation["os_probe_results"] = _check_os_fence()
        isolation["host_api_absent"] = True
        package = None
        while True:
            raw = sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1)
            if not raw:
                return 0
            if len(raw) > MAX_MESSAGE_BYTES or not raw.endswith(b"\n"):
                raise GameError("Worker request exceeds framing limit")
            message = json.loads(raw)
            sequence = message["sequence"]
            if message["action"] == "load" and package is None:
                package = validate_package(message["package"])
                context.set_time_limit(STARTUP_CPU_SECONDS)
                frame = json.loads(dispatch("load", package["code"], 0))
                validate_frame(frame, package)
                result = {"frame": frame, "isolation": isolation}
            elif message["action"] == "step" and package is not None:
                controls = validate_input(message["input"])
                dt = _number(message["dt"], 0, 0.1, "dt")
                context.set_time_limit(FRAME_CPU_SECONDS)
                frame = json.loads(dispatch("step", _json(controls), dt))
                result = validate_frame(frame, package)
            else:
                raise GameError("Invalid game lifecycle action")
            sys.stdout.write(_json({"sequence": sequence, "ok": True, "result": result}) + "\n")
            sys.stdout.flush()
    except Exception as error:
        try:
            sys.stdout.write(_json({"sequence": sequence, "ok": False,
                                   "error": str(error)[:600] or type(error).__name__}) + "\n")
            sys.stdout.flush()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
