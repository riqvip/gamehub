"""Request limits applied before JSON parsing or upload buffering."""

import asyncio
import json
import logging
import time

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from . import config

log = logging.getLogger("gamehub.requests")
if not log.handlers:
    log.addHandler(logging.StreamHandler())
log.setLevel(logging.INFO)
log.propagate = False


class BodyLimit(HTTPException):
    def __init__(self):
        super().__init__(413, "Request size limit exceeded")


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        limit = config.MAX_UPLOAD if path.endswith(("/mods/upload", "/code-mods/upload")) else 65536
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = -1
        if declared < 0 or declared > limit:
            return await JSONResponse({"detail": "Request too large"}, status_code=413)(scope, receive, send)
        count, started = 0, False
        began = time.monotonic()

        async def bounded_receive():
            nonlocal count
            message = await asyncio.wait_for(receive(), timeout=30)
            count += len(message.get("body", b""))
            if count > limit:
                raise BodyLimit()
            return message

        async def secured_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                    ),
                ]
                message["headers"] = list(message.get("headers", [])) + extra
                log.info(
                    json.dumps(
                        {
                            "method": scope["method"],
                            "path": path,
                            "status": message["status"],
                            "elapsed_ms": round((time.monotonic() - began) * 1000),
                        }
                    )
                )
            await send(message)

        try:
            await self.app(scope, bounded_receive, secured_send)
        except (BodyLimit, TimeoutError):
            if not started:
                await JSONResponse({"detail": "Request limit or receive timeout exceeded"}, status_code=413)(
                    scope, receive, secured_send
                )
