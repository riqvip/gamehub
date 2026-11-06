"""Approved runtime policy. Other games require a separately reviewed policy."""

from .. import config
from .base import GameTemplate

PALWORLD = GameTemplate(
    id="palworld",
    name="Palworld",
    image=config.PALWORLD_IMAGE,
    description="Native Linux dedicated server; asset mods remain unverified.",
    volumes={"data": "/palworld"},
    mods_dir="Pal/Content/Paks/~mods",
    rcon_supported=True,
    rcon_port=25575,
    rcon_env_key="ADMIN_PASSWORD",
)


def get_template(game_id):
    return PALWORLD if game_id == "palworld" else None


def list_templates():
    return [PALWORLD]
