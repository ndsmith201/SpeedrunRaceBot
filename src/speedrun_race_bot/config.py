from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    discord_token: str
    race_game: str
    seed_generator_command: str | None
    development_guild_id: int | None


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token or token == "replace_with_your_bot_token":
        raise RuntimeError("Set DISCORD_TOKEN in a .env file before starting the bot.")
    race_game = os.getenv("RACE_GAME", "").strip()
    if not race_game:
        raise RuntimeError("Set RACE_GAME in a .env file before starting the bot.")

    guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
    seed_generator_command = os.getenv("SEED_GENERATOR_COMMAND", "").strip() or None
    return Settings(
        discord_token=token,
        race_game=race_game,
        seed_generator_command=seed_generator_command,
        development_guild_id=int(guild_id) if guild_id else None,
    )
