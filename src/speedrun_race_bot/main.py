import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands

from speedrun_race_bot.config import load_settings
from speedrun_race_bot.race_options import StartOption, load_start_options
from speedrun_race_bot.seed_generation import ensure_seedbank

logger = logging.getLogger(__name__)


class SpeedrunRaceBot(commands.Bot):
    seed_generator_command: str | None
    start_options: list[StartOption]
    seedbank_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        self.seedbank_task = asyncio.create_task(
            ensure_seedbank(
                self.seed_generator_command,
                Path.cwd(),
                Path.cwd() / "seedbank",
                self.settings.race_game,
            ),
            name="populate-seedbank",
        )
        self.seedbank_task.add_done_callback(self._seedbank_task_done)
        await self.load_extension("speedrun_race_bot.cogs.races")
        if self.settings.development_guild_id:
            guild = discord.Object(id=self.settings.development_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    @staticmethod
    def _seedbank_task_done(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error:
            logger.error(
                "Background seed-bank generation failed",
                exc_info=(type(error), error, error.__traceback__),
            )


def run() -> None:
    settings = load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    intents = discord.Intents.default()
    bot = SpeedrunRaceBot(command_prefix="!", intents=intents)
    bot.settings = settings
    bot.seed_generator_command = settings.seed_generator_command
    bot.start_options = load_start_options(Path.cwd() / "config" / "config.yaml")
    bot.run(settings.discord_token)
