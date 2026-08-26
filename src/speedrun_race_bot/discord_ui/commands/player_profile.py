"""Commands for racer profile metadata shown in trackers."""

import discord
from discord import app_commands
from discord.ext import commands

from speedrun_race_bot.discord_ui.value_parsers import (
    is_country_flag_emoji,
    normalize_twitch_url,
)
from speedrun_race_bot.race.coordinator import RaceCoordinator


class PlayerProfileCommands(commands.Cog):
    def __init__(self, coordinator: RaceCoordinator) -> None:
        self.coordinator = coordinator

    @app_commands.command(name="flag", description="Save the flag shown next to your race name")
    async def flag(self, interaction: discord.Interaction, emoji: str) -> None:
        emoji = emoji.strip()
        if not is_country_flag_emoji(emoji):
            await interaction.response.send_message(
                "Choose a Discord country flag emoji, such as 🇺🇸 or 🇯🇵.", ephemeral=True
            )
            return
        self.coordinator.user_data.set_flag(interaction.user.id, emoji)
        await self._refresh_active_tracker(interaction)
        await interaction.response.send_message(f"Saved your flag as {emoji}.", ephemeral=True)

    @app_commands.command(name="stream", description="Save your Twitch stream link")
    async def stream(self, interaction: discord.Interaction, link: str) -> None:
        stream_url = normalize_twitch_url(link)
        if not stream_url:
            await interaction.response.send_message(
                "Enter a Twitch channel link such as https://www.twitch.tv/username.",
                ephemeral=True,
            )
            return
        self.coordinator.user_data.set_stream_url(interaction.user.id, stream_url)
        await self._refresh_active_tracker(interaction)
        await interaction.response.send_message(
            f"Saved your Twitch stream: {stream_url}", ephemeral=True
        )

    async def _refresh_active_tracker(self, interaction: discord.Interaction) -> None:
        race = self.coordinator.service.get(interaction.channel_id or 0)
        if race and interaction.user.id in race.entrants:
            await self.coordinator.race_message.update(race)
