"""Composition root for race workflows and Discord UI components."""

from discord.ext import commands

from speedrun_race_bot.discord_ui.commands import (
    AdminCommands,
    PlayerProfileCommands,
    RaceCommands,
    ReplayCommands,
)
from speedrun_race_bot.discord_ui.error_handler import CommandErrorHandler
from speedrun_race_bot.integrations.rando_api import RandoApiClient
from speedrun_race_bot.persistence import RaceRepository, UserRepository
from speedrun_race_bot.race.coordinator import RaceCoordinator
from speedrun_race_bot.race.state import RaceState


async def setup(bot: commands.Bot) -> None:
    """Create shared dependencies and register all race-related cogs and views."""
    project_directory = bot.project_directory
    database_path = project_directory / "database" / "bot.sqlite3"
    schema_path = project_directory / "database" / "schema.sql"
    races = RaceState(RaceRepository(database_path, schema_path))
    coordinator = RaceCoordinator(
        bot,
        races,
        bot.seed_generator_command,
        UserRepository(database_path, schema_path),
        RandoApiClient(bot.settings.api_base_url, bot.settings.api_key),
    )
    await bot.add_cog(RaceCommands(coordinator, bot.start_options))
    await bot.add_cog(PlayerProfileCommands(coordinator))
    await bot.add_cog(ReplayCommands(coordinator))
    await bot.add_cog(AdminCommands(coordinator))
    await bot.add_cog(CommandErrorHandler(bot, coordinator.service, coordinator.voice_announcer))
    bot.add_view(coordinator.join_view)
    bot.add_view(coordinator.running_view)
    bot.add_view(coordinator.async_view)
    coordinator.restore_persisted_races()
