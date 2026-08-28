"""Application-command error reporting and the race voice error cue."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from speedrun_race_bot.integrations.voice_announcer import VoiceAnnouncer
from speedrun_race_bot.race.state import RaceState

logger = logging.getLogger(__name__)


class CommandErrorHandler(commands.Cog):
    def __init__(self, bot: commands.Bot, races: RaceState, voice: VoiceAnnouncer) -> None:
        self.bot = bot
        self.races = races
        self.voice = voice

    @commands.Cog.listener()
    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        logger.error("Application command failed: %s", error)
        race = self.races.get(interaction.channel_id or 0, is_async=False)
        if interaction.guild and race:
            voice_client = interaction.guild.voice_client
            if (
                voice_client
                and voice_client.channel
                and voice_client.channel.id == race.voice_channel_id
            ):
                await self.voice.announce_ready_error(voice_client)
        if not interaction.response.is_done():
            await interaction.response.send_message("Something went wrong.", ephemeral=True)
