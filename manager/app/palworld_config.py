"""Conservative INI helpers retained for tooling; the API uses typed settings."""

import re


def parse_option_settings(content: str) -> dict[str, str]:
    if len(content) > 65536:
        raise ValueError("Configuration too large")
    match = re.search(r"^OptionSettings=\(([^\r\n]*)\)\s*$", content, re.MULTILINE)
    if not match:
        return {}
    tokens = re.findall(r'(\w+)=("[^"\\\r\n]*"|[^,()"\r\n]+)(?:,|$)', match.group(1))
    rebuilt = ",".join(k + "=" + v for k, v in tokens)
    if rebuilt != match.group(1):
        raise ValueError("Malformed OptionSettings")
    result = {}
    for key, value in tokens:
        if key in result:
            raise ValueError("Duplicate setting")
        result[key] = value[1:-1] if value.startswith('"') else value
    return result


def dump_option_settings(settings: dict[str, str]) -> str:
    items = []
    for key, value in settings.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", key):
            raise ValueError("Invalid setting name")
        value = str(value)
        if len(value) > 1000 or any(c in value for c in '\r\n"\\') or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid setting value")
        scalar = re.fullmatch(r"(?:True|False|[+-]?[0-9]+(?:\.[0-9]+)?)", value, flags=re.IGNORECASE)
        items.append(f"{key}={value}" if scalar else f'{key}="{value}"')
    return "[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(" + ",".join(items) + ")\n"
