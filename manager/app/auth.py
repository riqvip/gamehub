"""Argon2id authentication and persistent, revocable, CSRF-bound sessions."""

import hashlib
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request

from . import config
from .ip_gate import client_ip

ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def validate():
    os.umask(0o077)
    if not config.ADMIN_PASSWORD_HASH.startswith("$argon2id$"):
        raise RuntimeError("Set ADMIN_PASSWORD_HASH_FILE to a generated Argon2id hash")
    if len(config.CONTROLLER_TOKEN) < 43:
        raise RuntimeError("A random controller token of at least 32 bytes is required")
    if not 300 <= config.SESSION_SECONDS <= 86400:
        raise RuntimeError("SESSION_SECONDS must be 300..86400")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    with database() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, csrf TEXT, expires REAL);
        CREATE TABLE IF NOT EXISTS attempts (ip TEXT, at REAL);
        CREATE INDEX IF NOT EXISTS attempts_at ON attempts(at);
        CREATE TABLE IF NOT EXISTS audit (at REAL, actor TEXT, action TEXT, target TEXT, outcome TEXT);
        """)


@contextmanager
def database():
    db = sqlite3.connect(config.DATA_DIR / "web.sqlite", timeout=10)
    try:
        with db:
            yield db
    finally:
        db.close()


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def audit(action, target="", outcome="ok", actor=None):
    with database() as db:
        db.execute(
            "INSERT INTO audit VALUES (?, ?, ?, ?, ?)",
            (time.time(), actor or config.ADMIN_USER, action[:100], target[:200], outcome[:80]),
        )
        db.execute("DELETE FROM audit WHERE rowid <= (SELECT max(rowid) - 10000 FROM audit)")


def verify_login(username, password, ip):
    now = time.time()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM attempts WHERE at < ?", (now - 900,))
        per_ip = db.execute("SELECT count(*) FROM attempts WHERE ip=?", (ip,)).fetchone()[0]
        total = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
        if per_ip >= 5 or total >= 50:
            raise HTTPException(
                429, "Too many attempts. Try again in 15 minutes.", headers={"Retry-After": "900"}
            )
        db.execute("INSERT INTO attempts VALUES (?, ?)", (ip, now))
    try:
        valid = ph.verify(config.ADMIN_PASSWORD_HASH, password)
    except (VerificationError, InvalidHashError):
        valid = False
    valid = valid and secrets.compare_digest(username.encode(), config.ADMIN_USER.encode())
    audit("login", ip, "ok" if valid else "denied", "authentication")
    if not valid:
        raise HTTPException(401, "Invalid credentials")
    session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with database() as db:
        db.execute("DELETE FROM attempts WHERE ip=?", (ip,))
        db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        db.execute(
            "INSERT INTO sessions VALUES (?, ?, ?)", (digest(session), csrf, now + config.SESSION_SECONDS)
        )
    return session, csrf


def require_auth(request: Request):
    token = request.cookies.get("gamehub_session", "")
    with database() as db:
        row = db.execute("SELECT csrf, expires FROM sessions WHERE id=?", (digest(token),)).fetchone()
    if not row or row[1] < time.time():
        raise HTTPException(401, "Session expired. Sign in again.")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not secrets.compare_digest(request.headers.get("x-csrf-token", "").encode(), row[0].encode()):
            raise HTTPException(403, "Invalid CSRF token")
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            raise HTTPException(403, "Cross-origin request rejected")
    return {"username": config.ADMIN_USER, "csrf": row[0], "ip": client_ip(request)}
