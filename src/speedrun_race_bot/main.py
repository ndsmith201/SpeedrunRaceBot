import logging
from pathlib import Path

import discord
from discord.ext import commands

from speedrun_race_bot.config import load_settings
from speedrun_race_bot.race_options import StartOption, load_start_options


class SpeedrunRaceBot(commands.Bot):
    seed_generator_command: str | None
    start_options: list[StartOption]

    async def setup_hook(self) -> None:
        await self.load_extension("speedrun_race_bot.cogs.races")
        if self.settings.development_guild_id:
            guild = discord.Object(id=self.settings.development_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()


def run() -> None:
    settings = load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    intents = discord.Intents.default()
    bot = SpeedrunRaceBot(command_prefix="!", intents=intents)
    bot.settings = settings
    bot.seed_generator_command = settings.seed_generator_command
    bot.start_options = load_start_options(Path.cwd() / "config" / "race_options.yaml")
    bot.run(settings.discord_token)
