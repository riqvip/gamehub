"""Only typed Palworld runtime settings are exposed by the controller."""

from . import docker_service


def get_settings(server_id):
    settings = dict(docker_service.get_instance(server_id)["settings"])
    # Passwords are write-only in the HTTP API. Blank on PUT preserves them.
    settings["admin_password"] = ""  # nosec B105
    settings["server_password"] = ""  # nosec B105
    return settings
