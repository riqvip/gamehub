"""Private atomic state and checked paths; never adopt an existing game directory."""

import json
import os
import re
import tempfile
import threading
from pathlib import Path, PurePosixPath

_LOCK = threading.RLock()


def identifier(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value):
        raise ValueError("Invalid identifier")
    return value


def relative(value):
    if not value or "\\" in value or ":" in value or any(ord(c) < 32 for c in value):
        raise ValueError("Unsafe file path")
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in ("", ".", "..") for x in value.split("/")):
        raise ValueError("Unsafe file path")
    if any(len(x) > 180 for x in p.parts) or len(value) > 512:
        raise ValueError("File path too long")
    return p


def checked(root: Path, value: str = "") -> Path:
    root = Path(root)
    p = root / str(relative(value)) if value else root
    # Check every ancestor, including the configured root, without resolving links away.
    for ancestor in [p, *p.parents]:
        if ancestor.is_symlink():
            raise ValueError("Symlinks are not allowed")
    if p.exists() and not (p.is_dir() or p.is_file()):
        raise ValueError("Special files are not allowed")
    return p


def atomic_json(path: Path, value):
    atomic_bytes(path, json.dumps(value, indent=2).encode())


def atomic_bytes(path: Path, value: bytes):
    checked(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def read_json(path, default=None):
    checked(path)
    return json.loads(path.read_text()) if path.exists() else default
