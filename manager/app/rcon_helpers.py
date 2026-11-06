"""RCON is reached over the private game network; never through a host port."""

import csv
import io

from . import config, docker_service
from .rcon import rcon_command


def exec_rcon(server_id, command):
    inst = docker_service.get_instance(server_id)
    cont = docker_service.get_container(server_id)
    if not cont or cont.status != "running":
        raise ValueError("Game container is not running")
    address = cont.attrs["NetworkSettings"]["Networks"][config.GAME_NETWORK]["IPAddress"]
    if not address:
        raise ValueError("Game network address unavailable")
    return rcon_command(address, 25575, inst["settings"]["admin_password"], command, timeout=3)


def parse_players(game, raw):
    rows = list(csv.reader(io.StringIO(raw)))
    return [{"name": r[0], "uid": r[1], "steam_id": r[2]} for r in rows[1:] if len(r) == 3]
