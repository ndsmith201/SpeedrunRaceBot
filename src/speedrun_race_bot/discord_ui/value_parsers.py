"""Validation and normalization for values entered through Discord."""

import re
from urllib.parse import urlparse


def is_country_flag_emoji(value: str) -> bool:
    """Return whether a value is a two-regional-indicator country flag."""
    return len(value) == 2 and all("\U0001f1e6" <= character <= "\U0001f1ff" for character in value)


def normalize_twitch_url(value: str) -> str | None:
    """Return a canonical Twitch channel URL, or None for invalid links."""
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "twitch.tv",
        "www.twitch.tv",
    }:
        return None
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) != 1 or not re.fullmatch(r"[A-Za-z0-9_]{4,25}", path_parts[0]):
        return None
    if path_parts[0].casefold() in {
        "directory",
        "downloads",
        "jobs",
        "settings",
        "subscriptions",
        "videos",
    }:
        return None
    return f"https://www.twitch.tv/{path_parts[0]}"
