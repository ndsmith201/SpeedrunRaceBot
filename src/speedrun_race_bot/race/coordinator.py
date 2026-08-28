import asyncio
import logging
from datetime import UTC, datetime

import discord
from discord.ext import commands

from speedrun_race_bot.discord_ui.controls import AsyncRaceView, JoinRaceView, RunningRaceView
from speedrun_race_bot.discord_ui.race_tracker import RaceTracker
from speedrun_race_bot.discord_ui.value_parsers import async_race_close_time
from speedrun_race_bot.domain import Race, RaceStatus
from speedrun_race_bot.integrations.rando_api import RandoApiClient, RandoApiError
from speedrun_race_bot.integrations.voice_announcer import VoiceAnnouncer
from speedrun_race_bot.persistence import UserRepository
from speedrun_race_bot.race.countdown import RaceCountdown
from speedrun_race_bot.race.elo import EloService
from speedrun_race_bot.race.replay_storage import ReplayStorage
from speedrun_race_bot.race.results import RaceResults
from speedrun_race_bot.race.seed_delivery import SeedDelivery
from speedrun_race_bot.race.state import RaceState

logger = logging.getLogger(__name__)


class RaceCoordinator:
    def __init__(
        self,
        bot: commands.Bot,
        service: RaceState,
        seed_generator_command: str | None,
        user_data: UserRepository,
        rando_api: RandoApiClient,
    ) -> None:
        self.bot = bot
        self.service = service
        self.user_data = user_data
        self.rando_api = rando_api
        self.project_directory = bot.project_directory
        self.replays_directory = bot.settings.replays_folder
        self.join_view = JoinRaceView(self)
        self.running_view = RunningRaceView(self)
        self.async_view = AsyncRaceView(self)
        self.race_message = RaceTracker(
            bot, user_data, self.join_view, self.running_view, self.async_view
        )
        self.voice_announcer = VoiceAnnouncer()
        self.countdown = RaceCountdown(
            bot, service, self.race_message, rando_api, self.voice_announcer
        )
        self.seed_delivery = SeedDelivery(
            bot, self.race_message, seed_generator_command, self.project_directory
        )
        self.replays = ReplayStorage(service, self.race_message, self.replays_directory)
        self.results = RaceResults(
            service, user_data, EloService(user_data), rando_api, self.race_message
        )
        self.async_close_tasks: dict[int, asyncio.Task[None]] = {}

    async def create_race(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        voice_channel: discord.VoiceChannel,
        annotation: str | None,
        selected_options: dict[str, str | None],
    ) -> None:
        if not interaction.guild or not interaction.guild_id:
            await interaction.response.send_message(
                "Races can only be created in a server channel.", ephemeral=True
            )
            return
        if (
            channel.guild.id != interaction.guild_id
            or voice_channel.guild.id != interaction.guild_id
        ):
            await interaction.response.send_message(
                "Choose channels from this server.", ephemeral=True
            )
            return
        existing_race = self.service.get(channel.id)
        if existing_race and existing_race.status is not RaceStatus.COMPLETE:
            await interaction.response.send_message(
                "This channel already has an active race.", ephemeral=True
            )
            return
        preset = next(
            (
                value
                for name, value in selected_options.items()
                if name.casefold() == "randomizer preset"
            ),
            None,
        )
        if not preset:
            await interaction.response.send_message(
                "Choose a Randomizer preset so the race can be created in the API.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            api_name = await self.rando_api.ensure_user(interaction.user.name, interaction.user.id)
            self.user_data.ensure_user(interaction.user.id)
        except RandoApiError as error:
            logger.warning("Could not ensure API user %s: %s", interaction.user.id, error)
            await interaction.followup.send(
                f"I could not register you with the race API: {error}", ephemeral=True
            )
            return
        try:
            voice_client = interaction.guild.voice_client
            if voice_client and voice_client.is_connected():
                await voice_client.move_to(voice_channel)
            else:
                voice_client = await voice_channel.connect()
        except (discord.ClientException, discord.HTTPException) as error:
            await interaction.followup.send(
                f"I could not join {voice_channel.mention}: {error}", ephemeral=True
            )
            return
        try:
            await self.rando_api.create_current_race(preset)
            await self.rando_api.add_current_racer(api_name)
        except RandoApiError as error:
            logger.warning("Could not create current API race: %s", error)
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()
            await interaction.followup.send(
                f"I could not create the race in the API: {error}", ephemeral=True
            )
            return
        race = Race(
            guild_id=interaction.guild_id,
            channel_id=channel.id,
            voice_channel_id=voice_channel.id,
            interaction_id=interaction.id,
            host_id=interaction.user.id,
            game=self.bot.settings.race_game,
            category="",
            annotation=annotation.strip() if annotation else None,
        )
        race.start_options = {
            name: value for name, value in selected_options.items() if value is not None
        }
        is_custom_preset = preset.strip().casefold() == "custom"
        if self.seed_delivery.enabled and not is_custom_preset:
            race.seed_generation_in_progress = True
        try:
            self.service.create(race)
            self.service.join(race, interaction.user.id, interaction.user.display_name, api_name)
        except ValueError as error:
            if interaction.response.is_done():
                await interaction.followup.send(str(error), ephemeral=True)
            else:
                await interaction.response.send_message(str(error), ephemeral=True)
            return
        status_message = await self.race_message.create(race, channel)
        self.service.record_tracker_message(race, status_message.id)
        if self.seed_delivery.enabled and not is_custom_preset:
            self.seed_delivery.schedule(race, interaction.id)
        await self.voice_announcer.announce_player_joined(voice_client)
        confirmation = f"🏁 **{race.game}** lobby created in {channel.mention}."
        if interaction.response.is_done():
            await interaction.followup.send(confirmation, ephemeral=True)
        else:
            await interaction.response.send_message(confirmation, ephemeral=True)

    async def create_async_race(
        self,
        interaction: discord.Interaction,
        preset: str,
        closes_at_seconds: int,
    ) -> None:
        """Create a race in the current text channel and start it without a countdown."""
        channel = interaction.channel
        if (
            not interaction.guild
            or not interaction.guild_id
            or not isinstance(channel, discord.TextChannel)
        ):
            await interaction.response.send_message(
                "Async races can only be created in a server text channel.", ephemeral=True
            )
            return
        closes_at = async_race_close_time(closes_at_seconds)
        if not closes_at:
            await interaction.response.send_message(
                "Choose one of the available async race close durations.", ephemeral=True
            )
            return
        existing_race = self.service.get(channel.id)
        if existing_race and existing_race.status is not RaceStatus.COMPLETE:
            await interaction.response.send_message(
                "This channel already has an active race.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        self.user_data.ensure_user(interaction.user.id)

        race = Race(
            guild_id=interaction.guild_id,
            channel_id=channel.id,
            voice_channel_id=None,
            interaction_id=interaction.id,
            host_id=interaction.user.id,
            game=self.bot.settings.race_game,
            category="",
            async_closes_at=closes_at,
        )
        race.start_options = {"Randomizer preset": preset}
        is_custom_preset = preset.strip().casefold() == "custom"
        if self.seed_delivery.enabled and not is_custom_preset:
            race.seed_generation_in_progress = True
        try:
            self.service.create(race)
            self.service.join(race, interaction.user.id, interaction.user.display_name)
            self.service.start_async(race)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        status_message = await self.race_message.create(race, channel)
        self.service.record_tracker_message(race, status_message.id)
        pin_warning = ""
        try:
            await status_message.pin(reason=f"Async race {race.interaction_id}")
        except discord.HTTPException as error:
            logger.warning("Could not pin async race %s: %s", race.interaction_id, error)
            pin_warning = " I could not pin the tracker; check my Manage Messages permission."
        if self.seed_delivery.enabled and not is_custom_preset:
            self.seed_delivery.schedule(race, interaction.id)
        self._schedule_async_close(race)
        close_timestamp = int(closes_at.timestamp())
        await interaction.followup.send(
            f"🏁 Async **{race.game}** race started here and closes "
            f"<t:{close_timestamp}:F> (<t:{close_timestamp}:R>).{pin_warning}",
            ephemeral=True,
        )

    async def join_race(self, interaction: discord.Interaction) -> str:
        """Toggle the button-clicking user's membership in the tracker race."""
        race = self.service.get(interaction.channel_id or 0)
        if not race:
            return "There is no active race in this channel."
        if race.is_async and interaction.user.id in race.entrants:
            return "You already joined this async race."
        joined = interaction.user.id not in race.entrants
        try:
            if joined:
                self.user_data.ensure_user(interaction.user.id)
                if race.is_async:
                    self.service.join(race, interaction.user.id, interaction.user.display_name)
                else:
                    api_name = await self.rando_api.ensure_user(
                        interaction.user.name, interaction.user.id
                    )
                    await self.rando_api.add_current_racer(api_name)
                    self.service.join(
                        race,
                        interaction.user.id,
                        interaction.user.display_name,
                        api_name,
                    )
            else:
                entrant = race.entrants[interaction.user.id]
                await self.rando_api.remove_current_racer(entrant.api_name or interaction.user.name)
                self.service.leave(race, interaction.user.id)
        except (RandoApiError, ValueError) as error:
            return str(error)
        await self.race_message.update(race)
        if joined and interaction.guild:
            voice_client = interaction.guild.voice_client
            if (
                voice_client
                and voice_client.channel
                and voice_client.channel.id == race.voice_channel_id
            ):
                await self.voice_announcer.announce_player_joined(voice_client)
        return "You joined the race!" if joined else "You left the race."

    async def ready_racer(self, interaction: discord.Interaction) -> str:
        race = self.service.get(interaction.channel_id or 0)
        if not race:
            return "There is no active race in this channel."
        try:
            is_ready = self.service.set_ready(race, interaction.user.id)
        except ValueError as error:
            return str(error)
        await self.race_message.update(race)
        return "You are marked ready!" if is_ready else "You are no longer ready."

    async def save_replay(
        self, interaction: discord.Interaction, replay: discord.Attachment
    ) -> str:
        return await self.replays.save(interaction, replay)

    async def start_race(self, interaction: discord.Interaction, *, silent: bool = False) -> None:
        await self.countdown.start(interaction, silent=silent)

    async def close_race(self, race: Race) -> str:
        """Close an active race and clean up its live Discord/API resources."""
        self.countdown.cancel(race)
        self._cancel_async_close(race)
        if race.is_async and race.status is RaceStatus.RUNNING:
            result_error = await self.results.finalize_async_race(race)
            if result_error:
                logger.warning(
                    "Async race %s closed with incomplete finalization: %s",
                    race.interaction_id,
                    result_error,
                )
        self.service.close(race)
        await self.race_message.update(race)

        guild = self.bot.get_guild(race.guild_id)
        voice_client = guild.voice_client if guild else None
        if (
            voice_client
            and voice_client.is_connected()
            and voice_client.channel
            and voice_client.channel.id == race.voice_channel_id
        ):
            await voice_client.disconnect()

        if not race.api_race_finished:
            try:
                await self.rando_api.finish_current_race()
                race.api_race_finished = True
            except RandoApiError as error:
                logger.warning("Could not finalize API race while closing: %s", error)
                return (
                    f"Closed race `{race.interaction_id}` locally, but API finalization "
                    f"failed: {error}"
                )
        return f"Closed race `{race.interaction_id}`."

    def _schedule_async_close(self, race: Race) -> None:
        task = asyncio.create_task(
            self._close_async_at_deadline(race),
            name=f"close-async-race-{race.interaction_id}",
        )
        self.async_close_tasks[race.interaction_id] = task
        task.add_done_callback(
            lambda completed, race_id=race.interaction_id: self.async_close_tasks.pop(race_id, None)
        )

    def _cancel_async_close(self, race: Race) -> None:
        task = self.async_close_tasks.pop(race.interaction_id, None)
        if task and task is not asyncio.current_task():
            task.cancel()

    async def _close_async_at_deadline(self, race: Race) -> None:
        if not race.async_closes_at:
            return
        try:
            delay = max(0.0, (race.async_closes_at - datetime.now(UTC)).total_seconds())
            await asyncio.sleep(delay)
            if self.service.get(race.channel_id) is not race or race.closed:
                return
            result_error = await self.results.finalize_async_race(race)
            self.service.close(race)
            await self.race_message.update(race)
            channel = self.bot.get_channel(race.channel_id)
            if isinstance(channel, discord.TextChannel):
                message = f"🏁 Async race {race.interaction_id} is closed. Final results are up."
                if result_error:
                    message += f"\n⚠️ {result_error}"
                await channel.send(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Could not close async race %s", race.interaction_id)

    async def record_finish(self, interaction: discord.Interaction) -> str | None:
        return await self.results.record_finish(interaction)

    async def record_forfeit(self, interaction: discord.Interaction) -> str | None:
        return await self.results.record_forfeit(interaction)

    async def adjust_race_elo(self, race_id: int, ordered_user_ids: list[int]) -> str:
        return await self.results.adjust_elo(race_id, ordered_user_ids)
