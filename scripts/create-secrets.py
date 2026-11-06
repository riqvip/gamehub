#!/usr/bin/env python3
"""Generate individual secret files. Never print credentials or replace existing files."""

import argparse
import getpass
import os
import secrets
from pathlib import Path

from argon2 import PasswordHasher

parser = argparse.ArgumentParser()
parser.add_argument("directory", type=Path)
args = parser.parse_args()
password = getpass.getpass("Administrator password (at least 16 characters): ")
if len(password) < 16 or password != getpass.getpass("Confirm password: "):
    raise SystemExit("Passwords must match and contain at least 16 characters")
args.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
values = {
    "controller-token": secrets.token_urlsafe(32),
    "admin-password-hash": PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2).hash(password),
}
for name, value in values.items():
    path = args.directory / name
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
    with os.fdopen(fd, "w") as output:
        output.write(value + "\n")
print("Created private secret files. They must be readable by UID 1000 in the web container.")
