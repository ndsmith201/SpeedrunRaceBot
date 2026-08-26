"""Environment-backed application settings."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    discord_token: str
    race_game: str
    api_base_url: str
    api_key: str
    seed_generator_command: str | None
    development_guild_id: int | None
    replays_folder: Path


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token or token == "replace_with_your_bot_token":
        raise RuntimeError("Set DISCORD_TOKEN in a .env file before starting the bot.")
    race_game = os.getenv("RACE_GAME", "").strip()
    if not race_game:
        raise RuntimeError("Set RACE_GAME in a .env file before starting the bot.")
    api_base_url = os.getenv("API_BASE_URL", "").strip()
    if not api_base_url:
        raise RuntimeError("Set API_BASE_URL in a .env file before starting the bot.")
    api_key = os.getenv("API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set API_KEY in a .env file before starting the bot.")

    guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
    seed_generator_command = os.getenv("SEED_GENERATOR_COMMAND", "").strip() or None
    replays_folder = Path(os.getenv("REPLAYS_FOLDER", "./replays")).expanduser()
    if not replays_folder.is_absolute():
        replays_folder = Path.cwd() / replays_folder
    return Settings(
        discord_token=token,
        race_game=race_game,
        api_base_url=api_base_url,
        api_key=api_key,
        seed_generator_command=seed_generator_command,
        development_guild_id=int(guild_id) if guild_id else None,
        replays_folder=replays_folder,
    )
