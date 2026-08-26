"""Commands for uploading and downloading race replay files."""

import asyncio
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import discord
from discord import app_commands
from discord.ext import commands

from speedrun_race_bot.race.coordinator import RaceCoordinator


class ReplayCommands(commands.Cog):
    def __init__(self, coordinator: RaceCoordinator) -> None:
        self.coordinator = coordinator

    @app_commands.command(name="replay", description="Submit your finished-race replay")
    @app_commands.describe(replay="Your .sotnr replay file (maximum 100 KB)")
    async def replay(self, interaction: discord.Interaction, replay: discord.Attachment) -> None:
        await interaction.response.defer(ephemeral=True)
        result = await self.coordinator.save_replay(interaction, replay)
        await interaction.followup.send(result, ephemeral=True)

    @app_commands.command(name="replays", description="Download a race's submitted replays")
    @app_commands.describe(raceid="The race creation interaction ID")
    async def replays(self, interaction: discord.Interaction, raceid: str) -> None:
        await interaction.response.defer(ephemeral=True)
        race_id = raceid.strip()
        if not race_id.isdecimal():
            await interaction.followup.send("Enter a valid numeric race ID.", ephemeral=True)
            return

        replays_root = self.coordinator.replays_directory.resolve()
        replay_directory = (replays_root / race_id).resolve()
        if replay_directory.parent != replays_root or not replay_directory.is_dir():
            await interaction.followup.send(
                f"I couldn't find replay files for race `{race_id}`.", ephemeral=True
            )
            return

        with TemporaryDirectory(prefix="speedrun-replays-") as temporary_directory:
            archive_base = Path(temporary_directory) / f"replays-{race_id}"
            archive_path = await asyncio.to_thread(
                shutil.make_archive,
                str(archive_base),
                "zip",
                root_dir=replay_directory,
            )
            replay_archive = discord.File(archive_path, filename=f"replays-{race_id}.zip")
            try:
                await interaction.followup.send(file=replay_archive, ephemeral=True)
            finally:
                replay_archive.close()
