"""Authenticated, bounded requests to an ownership-verified game container only."""

import json

import httpx

from . import config
from . import docker_service as ds


def request(server_id, path, method="GET"):
    if (method, path) not in (("GET", "info"), ("GET", "players"), ("POST", "save")):
        raise ValueError("Unsupported game REST operation")
    cont = ds.get_container(server_id)
    if not cont or cont.status != "running":
        raise ValueError("Game container is not running")
    address = cont.attrs["NetworkSettings"]["Networks"][config.GAME_NETWORK]["IPAddress"]
    if not address:
        raise ValueError("Game network address unavailable")
    password = ds.get_instance(server_id)["settings"]["admin_password"]
    try:
        with httpx.stream(
            method,
            f"http://{address}:8212/v1/api/{path}",
            auth=("admin", password),
            timeout=3,
            trust_env=False,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise ValueError("Game REST request failed; check initialization and administrator password")
            data = bytearray()
            for part in response.iter_bytes():
                data.extend(part)
                if len(data) > 1024**2:
                    raise ValueError("Game REST response too large")
            return json.loads(data) if data else {}
    except httpx.HTTPError:
        raise OSError("Game REST API unavailable") from None


def game_info(server_id):
    try:
        value = request(server_id, "info")
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        # Older native instances may still lack REST until controlled recreation.
        from .rcon_helpers import exec_rcon

        text = exec_rcon(server_id, "Info")
        return {"version": text} if "Pal Server" in text or "Palworld" in text else {}


def players(server_id):
    try:
        data = request(server_id, "players")
        return [
            {
                "name": str(p.get("name", "")),
                "uid": str(p.get("playerId", "")),
                "steam_id": str(p.get("userId", "")),
            }
            for p in data.get("players", [])
            if isinstance(p, dict)
        ]
    except (OSError, ValueError):
        from .rcon_helpers import exec_rcon, parse_players

        return parse_players("palworld", exec_rcon(server_id, "ShowPlayers"))
