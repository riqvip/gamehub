#!/usr/bin/env python3
"""Disposable Wine/UE4SS/PWP experiment; never accepts a production data path.

Run with the development Python environment on a local x86-64 Linux Docker host.
Third-party code executes only inside the restricted game container. This is a
startup/save/restart smoke test, not multiplayer or mod gameplay acceptance.
"""

import hashlib
import json
import os
import secrets
import shutil
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

import docker
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "manager"))
from app.archives import copy_tree, extract_zip  # noqa: E402
from app.storage import checked  # noqa: E402

IMAGE = "thijsvanloef/palworld-server-docker@sha256:911ec2b0fd9a3392e9ab687833344d3cda025998cce7dab11a943fa4cedb3e3f"
LOADER_URL = "https://github.com/Okaetsu/RE-UE4SS/releases/download/2281fa31/UE4SS-Palworld-g2281fa31.zip"
LOADER_SHA = "f7543d57f8fdf5eab3731ac52121e6e7ff142fb3bfa17156e931037d0e44875b"
PWP_COMMIT = "dcc4811dc1117ef58a4f491d09c0513123ca0036"
PWP_URL = f"https://codeload.github.com/Matraweber/PalWorkPriority/zip/{PWP_COMMIT}"
PWP_SHA = "03f7e7ceaa9156b2029dc81a0d120debb2c34918fd89ea853f6c4ad2f252483a"


def download(url, expected, dest):
    deadline = time.monotonic() + 120
    digest = hashlib.sha256()
    size = 0
    # URLs are fixed reviewed sources, with a mandatory content hash. No credentials.
    with httpx.stream("GET", url, follow_redirects=True, timeout=20, trust_env=False) as response:
        response.raise_for_status()
        with dest.open("xb") as output:
            for chunk in response.iter_bytes(1024 * 1024):
                size += len(chunk)
                if size > 32 * 1024**2 or time.monotonic() > deadline:
                    raise ValueError("Release download exceeded its size/deadline limit")
                output.write(chunk)
                digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("Release checksum mismatch; do not bypass this check")


class Lab:
    def __init__(self, root, client):
        self.root, self.client = root, client
        self.owner = secrets.token_hex(24)
        self.password = secrets.token_urlsafe(32)
        self.game = root / "game"
        self.game.mkdir(mode=0o700)
        self.report = {
            "image": IMAGE,
            "loader_sha256": LOADER_SHA,
            "pwp_commit": PWP_COMMIT,
            "scope": "Empty disposable world, no clients; no gameplay compatibility claim",
            "stages": {},
        }

    def run(self, phase, ready=None):
        if phase != "install":
            # Readiness must come from this process, never an earlier appended log.
            priority_log = self.game / "Pal/Binaries/Win64/ue4ss/Mods/PalWorkPriority/priority.log"
            if priority_log.exists():
                priority_log.unlink()
        env = {
            "PUID": "1000",
            "PGID": "1000",
            "SERVER_PLATFORM": "Windows",
            "SETUP_ONLY": str(phase == "install").lower(),
            "UPDATE_ON_BOOT": "false",
            "USE_DEPOT_DOWNLOADER": "true",
            "MOD_ENABLED": "true",
            "MOD_UPDATE_ON_BOOT": "false",
            "MOD_USE_PALDEFENDER": "false",
            "BACKUP_ENABLED": "false",
            "AUTO_UPDATE_ENABLED": "false",
            "AUTO_REBOOT_ENABLED": "false",
            "AUTO_PAUSE_ENABLED": "false",
            "REST_API_ENABLED": "true",
            "REST_API_PORT": "8212",
            "RCON_ENABLED": "false",
            "ENABLE_PLAYER_LOGGING": "false",
            "ADMIN_PASSWORD": self.password,
            "SERVER_NAME": "Disposable Wine mod test",
            "PLAYERS": "2",
            "PORT": "8211",
            "COMMUNITY": "false",
            "LOG_FILTER_ENABLED": "false",
            "TZ": "UTC",
        }
        container = self.client.containers.create(
            IMAGE,
            name=f"gh-wine-test-{phase}-{secrets.token_hex(4)}",
            environment=env,
            labels={"io.gamehub.wine-test": self.owner},
            volumes={str(self.game): {"bind": "/palworld", "mode": "rw"}},
            network="bridge",
            user="1000:1000",
            privileged=False,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            init=True,
            mem_limit="3g",
            nano_cpus=2_000_000_000,
            pids_limit=512,
            restart_policy={"Name": "no"},
            tmpfs={"/tmp": "rw,nosuid,nodev,size=512m"},  # nosec B108
            log_config=docker.types.LogConfig(type="json-file", config={"max-size": "10m", "max-file": "2"}),
        )
        # No ports, socket, production data or credentials are mounted/published.
        (self.root / "active-container-id").write_text(container.id)
        try:
            container.start()
            deadline = time.monotonic() + (900 if phase == "install" else 180)
            next_progress = 0
            while time.monotonic() < deadline:
                container.reload()
                if container.status == "exited":
                    if phase != "install" or container.attrs["State"]["ExitCode"] != 0:
                        raise RuntimeError(f"{phase}: unexpected container exit")
                    if not (self.game / "PalServer.exe").is_file():
                        raise RuntimeError("Installer omitted the Windows server executable")
                    return None
                if phase != "install":
                    address = container.attrs["NetworkSettings"]["Networks"]["bridge"]["IPAddress"]
                    # Disable environment proxies; this is only this newly created container's IP.
                    with httpx.Client(
                        base_url=f"http://{address}:8212/v1/api",
                        auth=("admin", self.password),
                        timeout=3,
                        trust_env=False,
                    ) as http:
                        try:
                            info = http.get("/info")
                            info.raise_for_status()
                        except httpx.HTTPError:
                            pass  # Bounded readiness polling; no installation retry.
                        else:
                            return ready(http, info.json())
                if time.monotonic() >= next_progress:
                    print(f"{phase}: running (bounded; detailed output retained locally)", flush=True)
                    next_progress = time.monotonic() + 15
                time.sleep(2)
            raise TimeoutError(f"{phase}: deadline exceeded; no automatic retry")
        finally:
            container.reload()
            if container.labels.get("io.gamehub.wine-test") != self.owner:
                raise RuntimeError("Test container ownership changed; refusing further operations")
            if container.status == "running":
                container.stop(timeout=60)
            container.reload()
            output = container.logs().decode(errors="replace").replace(self.password, "[redacted]")
            (self.root / f"{phase}.log").write_text(output)
            self.report["stages"][phase] = {
                "exit_code": container.attrs["State"]["ExitCode"],
                "oom": container.attrs["State"]["OOMKilled"],
                "rest_save_logged": "endpoint /v1/api/save OK" in output,
                "rest_shutdown_logged": "endpoint /v1/api/shutdown OK" in output,
            }
            container.remove(v=False, force=False)
            (self.root / "active-container-id").unlink()
            self.save_report()

    def save_report(self):
        (self.root / "result.json").write_text(json.dumps(self.report, indent=2) + "\n")

    def check_ready(self, http, info):
        mods = self.game / "Pal/Binaries/Win64/ue4ss/Mods/PalWorkPriority"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            log = (mods / "priority.log").read_text() if (mods / "priority.log").exists() else ""
            if "PWP_READY version=0.5.0" in log and "role=authority settings=available" in log:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Pal Work Priority did not report dedicated-server readiness")
        players = http.get("/players")
        players.raise_for_status()
        unauthenticated = http.post("/save", auth=None)
        if unauthenticated.status_code not in (401, 403):
            raise RuntimeError("Unauthenticated REST save was not rejected")
        self.report["unauthenticated_save_rejected"] = True
        response = http.post("/save")
        response.raise_for_status()
        self.report["info"] = info
        self.report["pwp_authority_ready"] = True
        print("PASS: authenticated info/players/save and PWP server authority readiness", flush=True)
        return info


def main():
    if os.getuid() != 1000 or os.getgid() != 1000:
        raise RuntimeError("Run as local UID/GID 1000, never sudo; game test UID is fixed at 1000")
    repo = Path(__file__).resolve().parents[1]
    validation = checked(repo, ".validation")
    validation.mkdir(exist_ok=True)
    if shutil.disk_usage(validation).free < 16 * 1024**3:
        raise RuntimeError("At least 16 GiB free space required")
    root = checked(validation, "wine-mod-test-" + secrets.token_hex(6))
    root.mkdir(mode=0o700)
    print("Disposable test output:", root, flush=True)
    # A fixed local socket avoids accidentally selecting a remote production Docker context.
    lab = Lab(root, docker.DockerClient(base_url="unix:///var/run/docker.sock", timeout=30))
    try:
        with (root / "pull.log").open("w") as output:
            # Fixed Docker command and immutable image; no shell or caller-supplied arguments.
            subprocess.run(  # nosec B603 B607
                ["docker", "--host", "unix:///var/run/docker.sock", "pull", IMAGE],
                stdout=output,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=180,
            )
        lab.run("install")
        for url, digest, name in ((LOADER_URL, LOADER_SHA, "loader"), (PWP_URL, PWP_SHA, "pwp")):
            download(url, digest, root / f"{name}.zip")
            extract_zip(root / f"{name}.zip", root / name, 128 * 1024**2, 10000, time.monotonic() + 60)
        win64 = lab.game / "Pal/Binaries/Win64"
        shutil.copyfile(root / "loader/dwmapi.dll", win64 / "dwmapi.dll")
        copy_tree(root / "loader/ue4ss", win64 / "ue4ss")
        mods = win64 / "ue4ss/Mods"
        copy_tree(root / f"pwp/PalWorkPriority-{PWP_COMMIT}/Scripts", mods / "PalWorkPriority/Scripts")
        (mods / "PalWorkPriority/enabled.txt").touch()
        (mods / "mods.txt").write_text("PalWorkPriority : 1\n")
        first = lab.run("boot", lab.check_ready)
        second = lab.run("restart", lab.check_ready)
        if not first.get("worldguid") or first["worldguid"] != second.get("worldguid"):
            raise RuntimeError("World identity was not preserved across container recreation")
        for phase in ("boot", "restart"):
            result = lab.report["stages"][phase]
            if result["oom"] or not result["rest_save_logged"] or not result["rest_shutdown_logged"]:
                raise RuntimeError(f"{phase}: clean save/shutdown not established")
        lab.report["result"] = "PASS: startup/save/container recreation; multiplayer gameplay untested"
        print(lab.report["result"], flush=True)
    except BaseException as exc:
        lab.report["result"] = "FAILED: " + str(exc).replace(lab.password, "[redacted]")[:500]
        raise
    finally:
        lab.save_report()


if __name__ == "__main__":
    main()
