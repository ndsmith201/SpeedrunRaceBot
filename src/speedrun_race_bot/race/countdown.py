"""Race-start validation, countdown animation, and timer activation."""

import asyncio
import logging

import discord
from discord.ext import commands

from speedrun_race_bot.discord_ui.race_tracker import RaceTracker
from speedrun_race_bot.domain import Race
from speedrun_race_bot.integrations.rando_api import RandoApiClient
from speedrun_race_bot.integrations.voice_announcer import VoiceAnnouncer
from speedrun_race_bot.race.state import RaceState

logger = logging.getLogger(__name__)


class RaceCountdown:
    def __init__(
        self,
        bot: commands.Bot,
        races: RaceState,
        tracker: RaceTracker,
        api: RandoApiClient,
        voice: VoiceAnnouncer,
    ) -> None:
        self.bot = bot
        self.races = races
        self.tracker = tracker
        self.api = api
        self.voice = voice
        self.tasks: dict[int, asyncio.Task[None]] = {}

    async def start(self, interaction: discord.Interaction, *, silent: bool = False) -> None:
        race = self.races.get(interaction.channel_id or 0)
        start_error = self.races.validate_start(race, interaction.user.id)
        if start_error:
            await self._respond_to_start_error(interaction, race, start_error, silent)
            return
        if not race:
            return
        race.countdown_in_progress = True
        race.countdown_starter_id = interaction.user.id
        self.races.save(race)
        await self.tracker.update(race)
        task = asyncio.create_task(self._run(race))
        self.tasks[race.interaction_id] = task
        task.add_done_callback(
            lambda completed, race_id=race.interaction_id: self.tasks.pop(race_id, None)
        )
        if not silent:
            await interaction.response.send_message("Race countdown started!")

    def cancel(self, race: Race) -> None:
        task = self.tasks.pop(race.interaction_id, None)
        if task:
            task.cancel()
        race.countdown_in_progress = False
        race.countdown_value = None
        race.countdown_starter_id = None
        self.races.save(race)

    async def _run(self, race: Race) -> None:
        try:
            channel = self.bot.get_channel(race.channel_id)
            if not isinstance(channel, discord.TextChannel) or not race.status_message_id:
                return
            guild = self.bot.get_guild(race.guild_id)
            voice_client = guild.voice_client if guild else None
            if (
                voice_client
                and voice_client.channel
                and voice_client.channel.id == race.voice_channel_id
            ):
                await self.voice.announce_random_countdown(voice_client)
            for count in (3, 2, 1):
                race.countdown_value = count
                self.races.save(race)
                await self.tracker.update(race)
                await asyncio.sleep(0.8)
            race.countdown_value = None
            race.countdown_in_progress = False
            await self.api.start_current_race()
            self.races.start(race, race.countdown_starter_id or race.host_id)
            race.countdown_starter_id = None
            race.show_go_emoji = True
            self.races.save(race)
            await self.tracker.update(race)
            await asyncio.sleep(0.8)
            race.show_go_emoji = False
            self.races.save(race)
            await self.tracker.update(race)
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()
        except Exception:
            race.countdown_in_progress = False
            race.countdown_value = None
            race.countdown_starter_id = None
            self.races.save(race)
            logger.exception("Could not complete countdown for %s", race.game)
            await self.tracker.update(race)

    async def _respond_to_start_error(
        self,
        interaction: discord.Interaction,
        race: Race | None,
        error: str,
        silent: bool,
    ) -> None:
        if error.startswith("Every racer") and interaction.guild and race:
            voice_client = interaction.guild.voice_client
            if (
                voice_client
                and voice_client.channel
                and voice_client.channel.id == race.voice_channel_id
            ):
                await self.voice.announce_ready_error(voice_client)
        if silent:
            await interaction.followup.send(error, ephemeral=True)
        else:
            await interaction.response.send_message(error, ephemeral=True)
