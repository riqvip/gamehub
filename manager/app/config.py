"""Environment configuration. Secrets may be mounted as individual files."""

import os
from pathlib import Path


def secret(name: str) -> str:
    filename = os.getenv(name + "_FILE")
    return Path(filename).read_text().strip() if filename else os.getenv(name, "")


DATA_DIR = Path(os.getenv("DATA_DIR", "/state"))
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/configuration"))
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/backups"))
GAME_ROOT = Path(os.getenv("GAME_ROOT", "/games"))
HOST_GAME_ROOT = os.getenv("HOST_GAME_ROOT", "/opt/data/palworld/gamehub")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD_HASH = secret("ADMIN_PASSWORD_HASH")
CONTROLLER_TOKEN = secret("CONTROLLER_TOKEN")
CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://controller:8001")
TRUSTED_PROXIES = os.getenv("TRUSTED_PROXIES", "")
ADMIN_ALLOWED_IPS = os.getenv("ADMIN_ALLOWED_IPS", "")
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],homeserver").split(",")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
SESSION_SECONDS = int(os.getenv("SESSION_SECONDS", "3600"))
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_BYTES", str(128 * 1024**2)))
MAX_EXTRACTED = int(os.getenv("MAX_EXTRACTED_BYTES", str(512 * 1024**2)))
MAX_FILES = int(os.getenv("MAX_ARCHIVE_FILES", "2048"))
DOWNLOAD_HOSTS = frozenset(
    x.strip().lower() for x in os.getenv("MOD_DOWNLOAD_HOSTS", "").split(",") if x.strip()
)
PALWORLD_IMAGE = os.getenv("PALWORLD_IMAGE", "")
PALWORLD_WINE_IMAGE = os.getenv(
    "PALWORLD_WINE_IMAGE",
    "thijsvanloef/palworld-server-docker@sha256:911ec2b0fd9a3392e9ab687833344d3cda025998cce7dab11a943fa4cedb3e3f",
)
GAME_NETWORK = os.getenv("GAME_NETWORK", "gamehub-games")
GAME_BIND_IP = os.getenv("GAME_BIND_IP", "127.0.0.1")
GAME_MEMORY = os.getenv("GAME_MEMORY", "16g")
GAME_CPUS = int(os.getenv("GAME_CPUS", "4"))
INSTALL_TIMEOUT = int(os.getenv("INSTALL_TIMEOUT_SECONDS", "1800"))
INSTALL_BACKEND = os.getenv("INSTALL_BACKEND", "depotdownloader")
MIN_FREE_BYTES = int(os.getenv("MIN_FREE_BYTES", str(12 * 1024**3)))
BACKUP_MAX_BYTES = int(os.getenv("BACKUP_MAX_BYTES", str(16 * 1024**3)))
