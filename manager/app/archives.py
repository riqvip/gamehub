"""Bounded ZIP validation with no links, special files, duplicates or traversal."""

import shutil
import stat
import time
import zipfile
from pathlib import Path

from .storage import checked, relative


def extract_zip(source, target: Path, max_bytes, max_files, deadline=None):
    total = 0
    seen = set()
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > max_files:
            raise ValueError("Archive contains too many entries")
        for item in members:
            name = item.filename.rstrip("/") if item.is_dir() else item.filename
            relative(name)
            key = name.casefold()
            if key in seen:
                raise ValueError("Duplicate archive path")
            seen.add(key)
            mode = item.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if (
                kind not in (0, stat.S_IFREG, stat.S_IFDIR)
                or (kind == stat.S_IFDIR) != item.is_dir()
                and kind != 0
            ):
                raise ValueError("Archive links and special files are forbidden")
            if item.flag_bits & 1:
                raise ValueError("Encrypted archives are unsupported")
            total += item.file_size
            if total > max_bytes or item.file_size > max_bytes:
                raise ValueError("Archive extracted size limit exceeded")
            if item.file_size > max(1, item.compress_size) * 300:
                raise ValueError("Suspicious archive compression ratio")
        written = 0
        for item in members:
            path = checked(target, item.filename.rstrip("/"))
            if item.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            size = 0
            with archive.open(item) as src, path.open("xb") as dst:
                while chunk := src.read(1024 * 1024):
                    size += len(chunk)
                    written += len(chunk)
                    if (
                        written > max_bytes
                        or size > item.file_size
                        or deadline
                        and time.monotonic() > deadline
                    ):
                        raise ValueError("Archive extraction limit or deadline exceeded")
                    dst.write(chunk)
            if size != item.file_size:
                raise ValueError("Archive integrity failure")
    return written


def files(root: Path):
    for path in sorted(root.rglob("*")):
        checked(root, path.relative_to(root).as_posix())
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise ValueError("Hardlinked files are forbidden")
            yield path


def copy_tree(source: Path, target: Path):
    for path in files(source):
        dest = checked(target, path.relative_to(source).as_posix())
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest, follow_symlinks=False)
