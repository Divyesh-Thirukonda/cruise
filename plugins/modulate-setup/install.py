#!/usr/bin/env python3
"""Register this local Codex plugin; no native Modulate services are installed."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

NAME = "modulate-setup"
FILES = (
    ".codex-plugin/plugin.json", "README.md", "install.py", "setup-prompt.txt",
    "skills/modulate-setup/SKILL.md",
    "skills/modulate-setup/agents/openai.yaml",
    "skills/modulate-setup/references/native-setup.md",
    "skills/modulate-setup/scripts/inspect_setup.py",
)


def package_files(source):
    """Accept only the known package files, never recursive private state."""
    source = source.resolve()
    data = {}
    for relative in FILES:
        path = source / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source):
            raise ValueError(f"Invalid package file: {relative}")
        data[relative] = path.read_bytes()
    manifest = json.loads(data[".codex-plugin/plugin.json"])
    if manifest.get("name") != NAME or manifest.get("skills") != "./skills/":
        raise ValueError("This is not the Modulate Setup plugin")
    version = manifest.get("version", "")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid plugin version")
    return version, data


def atomic_json(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix=".modulate-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _install_locked(source, home, *, apply=False):
    home = home.expanduser().resolve()
    version, data = package_files(source)
    target = home / ".codex" / "plugins" / NAME / version
    catalog = home / ".agents" / "plugins" / "marketplace.json"
    for path in (target, catalog):
        if path.is_symlink() or not path.resolve().is_relative_to(home):
            raise ValueError("Refusing a plugin path outside the selected home")
    original = catalog.read_bytes() if catalog.exists() else None
    marketplace = json.loads(original) if original else {
        "name": "modulate-local", "interface": {"displayName": "Modulate"}, "plugins": [],
    }
    if not isinstance(marketplace, dict) or not isinstance(marketplace.get("plugins"), list) or not marketplace.get("name"):
        raise ValueError("Existing marketplace is not a supported catalog; it was left unchanged")
    relative = "./" + target.relative_to(home).as_posix()
    entry = {
        "name": NAME, "source": {"source": "local", "path": relative},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }
    matches = [item for item in marketplace["plugins"] if isinstance(item, dict) and item.get("name") == NAME]
    if len(matches) > 1 or (matches and matches[0] != entry):
        raise ValueError("A different Modulate Setup catalog entry exists; it was left unchanged")
    if target.exists():
        if not target.is_dir() or any(p.is_symlink() for p in target.rglob("*")):
            raise ValueError("Existing plugin directory is not a regular package; it was left unchanged")
        current = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
        if current != data:
            raise ValueError("Different files exist at the plugin destination; they were left unchanged")
    if not matches:
        marketplace["plugins"].append(entry)
    result = {"mode": "install" if apply else "preview", "plugin": str(target), "catalog": str(catalog), "version": version}
    if not apply:
        return result
    created = False
    try:
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".modulate-stage-", dir=target.parent))
            try:
                for name, content in data.items():
                    output = staging / name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(content)
                # A concurrent install must not replace another folder.
                staging.rename(target)
                created = True
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        if not matches:
            catalog.parent.mkdir(parents=True, exist_ok=True)
            # Refuse to overwrite a catalog changed after it was inspected.
            current = catalog.read_bytes() if catalog.exists() else None
            if current != original:
                raise ValueError("The plugin catalog changed during installation; retry after reviewing it")
            if original is not None:
                backup = catalog.with_name(f"marketplace.modulate-backup-{time.time_ns()}.json")
                with backup.open("xb") as stream:
                    stream.write(original)
                backup.chmod(0o600)
                result["catalog_backup"] = str(backup)
            atomic_json(catalog, marketplace)
        result["next"] = "Restart Codex, then install/enable Modulate Setup from the local Plugins source."
        return result
    except Exception as error:
        if created:
            # A user or another tool may already have added files. Never remove
            # the destination as failure cleanup; the next run can reuse it.
            raise ValueError(f"Catalog registration did not complete. Plugin files remain at {target}; review and retry. {error}") from error
        raise


def install(source, home, *, apply=False):
    if not apply:
        return _install_locked(source, home, apply=False)
    # Serialize this installer's read/modify/write operations. The separate
    # byte check also detects other writers before the final atomic replacement.
    try:
        import fcntl
    except ImportError as error:
        raise ValueError("This local installer requires macOS or Linux") from error
    package_files(source)
    home = home.expanduser().resolve()
    directory = home / ".agents" / "plugins"
    if not directory.resolve().is_relative_to(home):
        raise ValueError("Refusing a plugin catalog outside the selected home")
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".modulate-install.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _install_locked(source, home, apply=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Copy this package and register it in your personal plugin catalog")
    args = parser.parse_args()
    try:
        result = install(Path(__file__).resolve().parent, Path.home(), apply=args.install)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(1, f"Setup plugin was not installed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
