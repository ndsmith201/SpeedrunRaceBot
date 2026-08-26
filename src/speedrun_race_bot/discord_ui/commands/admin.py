"""Administrator-only Elo and season maintenance commands."""

import re

import discord
from discord import app_commands
from discord.ext import commands

from speedrun_race_bot.race.coordinator import RaceCoordinator


class AdminCommands(commands.Cog):
    def __init__(self, coordinator: RaceCoordinator) -> None:
        self.coordinator = coordinator

    @app_commands.command(
        name="eloadjust", description="Correct a completed race's finish order and Elo"
    )
    @app_commands.describe(
        raceid="The race creation interaction ID",
        players="Every racer in finish order, as mentions or IDs",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def elo_adjust(self, interaction: discord.Interaction, raceid: str, players: str) -> None:
        race_id = raceid.strip()
        if not race_id.isdecimal():
            await interaction.response.send_message(
                "Enter a valid numeric race ID.", ephemeral=True
            )
            return

        player_ids: list[int] = []
        for token in filter(None, re.split(r"[\s,]+", players.strip())):
            match = re.fullmatch(r"<@!?(\d+)>|(\d+)", token)
            if not match:
                await interaction.response.send_message(
                    f"I couldn't read `{token}`. Use Discord mentions or numeric user IDs, "
                    "separated by spaces or commas.",
                    ephemeral=True,
                )
                return
            player_ids.append(int(match.group(1) or match.group(2)))

        await interaction.response.defer(ephemeral=True)
        result = await self.coordinator.adjust_race_elo(int(race_id), player_ids)
        await interaction.followup.send(result, ephemeral=True)

    @app_commands.command(
        name="newseason", description="Back up user data and reset every Elo rating"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def new_season(self, interaction: discord.Interaction) -> None:
        backup_directory = self.coordinator.project_directory / "database" / "backups"
        backup_path = self.coordinator.user_data.start_new_season(backup_directory)
        await interaction.response.send_message(
            f"New season started. Elo ratings were reset to 1200. Backup: `{backup_path.name}`",
            ephemeral=True,
        )
