"""Controller accepts only typed, explicit game capabilities."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginRequest(Strict):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class Settings(Strict):
    server_name: str = Field(
        default="GameHub Palworld", min_length=1, max_length=80, pattern=r'^[^\r\n"\\\x00-\x1f]+$'
    )
    description: str = Field(default="Managed by GameHub", max_length=200, pattern=r'^[^\r\n"\\\x00-\x1f]*$')
    players: int = Field(default=16, ge=1, le=32)
    server_password: str = Field(default="", max_length=128, pattern=r'^[^\r\n"\\\x00-\x1f]*$')
    admin_password: str = Field(min_length=16, max_length=128, pattern=r'^[^\r\n"\\\x00-\x1f]+$')


class CreateServerRequest(Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    game: Literal["palworld"] = "palworld"
    game_port: int = Field(default=8211, ge=1024, le=65535)
    runtime: Literal["native-linux", "windows-wine"] = "native-linux"
    acknowledge_code_mods: bool = False
    settings: Settings


class RuntimeChange(Strict):
    confirmation: str
    acknowledge_code_mods: bool = False
    action: Literal["convert", "rollback"] = "convert"


class ActionRequest(Strict):
    action: Literal["start", "stop", "restart", "install", "update", "cancel", "remove"]
    confirmation: str = ""


class ModMetadata(Strict):
    name: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=1000)
    version: str = Field(default="unknown", max_length=80)
    author: str = Field(default="unknown", max_length=100)
    source: str = Field(default="local upload", max_length=500)
    dependencies: list[str] = Field(default_factory=list, max_length=40)


class ModAction(Strict):
    action: Literal["enable", "disable", "remove", "rollback"]
    acknowledge_unverified: bool = False


class URLInstall(Strict):
    url: str = Field(max_length=2048)
    filename: str = Field(max_length=180)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    update_id: str = ""


class RestoreRequest(Strict):
    filename: str = Field(max_length=180)
    confirmation: str = ""
    dry_run: bool = True


class BackupPolicy(Strict):
    interval_hours: int = Field(default=0, ge=0, le=720)
    retain: int = Field(default=7, ge=1, le=100)
