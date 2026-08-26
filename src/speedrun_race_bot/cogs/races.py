import asyncio
import logging
import secrets
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from speedrun_race_bot.cogs.commands import RaceCommands
from speedrun_race_bot.helpers import finish_time_to_milliseconds
from speedrun_race_bot.models import Race, RaceStatus
from speedrun_race_bot.seed_generation import SEEDBANK_PRESET, ensure_seedbank, run_seed_command
from speedrun_race_bot.services.races import RaceService
from speedrun_race_bot.services.rando_api import RandoApiClient, RandoApiError
from speedrun_race_bot.services.user_data import UserDataService
from speedrun_race_bot.services.voice import VoiceAnnouncer
from speedrun_race_bot.views import JoinRaceView, RaceMessage, RunningRaceView

logger = logging.getLogger(__name__)


class RaceCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        service: RaceService,
        seed_generator_command: str | None,
        user_data: UserDataService,
        rando_api: RandoApiClient,
    ) -> None:
        self.bot = bot
        self.service = service
        self.seed_generator_command = seed_generator_command
        self.user_data = user_data
        self.rando_api = rando_api
        self.project_directory = Path.cwd()
        self.seeds_directory = self.project_directory / "seeds"
        self.seedbank_directory = self.project_directory / "seedbank"
        self.replays_directory = bot.settings.replays_folder
        self.join_view = JoinRaceView(self)
        self.running_view = RunningRaceView(self)
        self.race_message = RaceMessage(bot, user_data, self.join_view, self.running_view)
        self.voice_announcer = VoiceAnnouncer()
        self.seed_tasks: set[asyncio.Task[None]] = set()
        self.seedbank_claim_lock = asyncio.Lock()
        self.countdown_tasks: dict[int, asyncio.Task[None]] = {}

    async def generate_and_attach_seed(self, race: Race, interaction_id: int) -> None:
        """Generate the seed without delaying creation of the race lobby."""
        try:
            if self._uses_seedbank(race):
                seed_path = await self._claim_seedbank_seed()
                self._schedule_seedbank_refill()
            else:
                seed_path = await run_seed_command(
                    self.seed_generator_command or "",
                    race,
                    interaction_id,
                    self.project_directory,
                    self.seeds_directory,
                )
            race.seed_filename = seed_path.name
            race.seed_generation_in_progress = False

            if race.closed:
                seed_path.unlink(missing_ok=True)
                return

            channel = self.bot.get_channel(race.channel_id)
            if isinstance(channel, discord.TextChannel) and race.status_message_id:
                seed_message = await channel.send(
                    file=discord.File(seed_path, filename=seed_path.name)
                )
                race.seed_url = seed_message.attachments[0].url
                await self.race_message.update(race)
            seed_path.unlink()
        except Exception:
            race.seed_generation_in_progress = False
            race.seed_generation_error = True
            logger.exception("Seed generation command failed for %s — %s", race.game, race.category)
            await self.race_message.update(race)

    @staticmethod
    def _uses_seedbank(race: Race) -> bool:
        preset = next(
            (
                value
                for name, value in race.start_options.items()
                if name.casefold() == "randomizer preset"
            ),
            "",
        )
        return preset.casefold() == SEEDBANK_PRESET

    async def _claim_seedbank_seed(self) -> Path:
        async with self.seedbank_claim_lock:
            candidates = [
                path
                for path in self.seedbank_directory.rglob("*")
                if path.is_file() and path.name != ".gitkeep"
            ]
            if not candidates:
                await ensure_seedbank(
                    self.seed_generator_command,
                    self.project_directory,
                    self.seedbank_directory,
                    self.bot.settings.race_game,
                    minimum_seeds=1,
                )
                candidates = [
                    path
                    for path in self.seedbank_directory.rglob("*")
                    if path.is_file() and path.name != ".gitkeep"
                ]
            if not candidates:
                raise RuntimeError("The seed bank is empty.")

            source_path = secrets.choice(candidates)
            self.seeds_directory.mkdir(parents=True, exist_ok=True)
            claimed_path = self.seeds_directory / source_path.name
            await asyncio.to_thread(source_path.replace, claimed_path)
            logger.info("Claimed seed-bank file: %s", source_path.name)
            return claimed_path

    def _schedule_seedbank_refill(self) -> None:
        task = asyncio.create_task(self._refill_seedbank(), name="refill-seedbank")
        self.seed_tasks.add(task)
        task.add_done_callback(self.seed_tasks.discard)

    async def _refill_seedbank(self) -> None:
        try:
            await ensure_seedbank(
                self.seed_generator_command,
                self.project_directory,
                self.seedbank_directory,
                self.bot.settings.race_game,
            )
        except Exception:
            logger.exception("Could not replenish the seed bank")

    async def run_countdown(self, race: Race) -> None:
        """Show the three countdown thumbnails, then begin the race timer on Go."""
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
                await self.voice_announcer.announce_random_countdown(voice_client)
            for count in (3, 2, 1):
                race.countdown_value = count
                await self.race_message.update(race)
                await asyncio.sleep(0.8)
            race.countdown_value = None
            race.countdown_in_progress = False
            await self.rando_api.start_current_race()
            self.service.start(race, race.countdown_starter_id or race.host_id)
            race.countdown_starter_id = None
            race.show_go_emoji = True
            await self.race_message.update(race)
            await asyncio.sleep(0.8)
            race.show_go_emoji = False
            await self.race_message.update(race)
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()
        except Exception:
            race.countdown_in_progress = False
            race.countdown_value = None
            race.countdown_starter_id = None
            logger.exception("Could not complete countdown for %s", race.game)
            await self.race_message.update(race)

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
            await self.rando_api.ensure_user(interaction.user.name, interaction.user.id)
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
            await self.rando_api.add_current_racer(interaction.user.name)
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
        if self.seed_generator_command and not is_custom_preset:
            race.seed_generation_in_progress = True
        try:
            self.service.create(race)
            self.service.join(race, interaction.user.id, interaction.user.display_name)
        except ValueError as error:
            if interaction.response.is_done():
                await interaction.followup.send(str(error), ephemeral=True)
            else:
                await interaction.response.send_message(str(error), ephemeral=True)
            return
        await self.race_message.create(race, channel)
        if self.seed_generator_command and not is_custom_preset:
            task = asyncio.create_task(self.generate_and_attach_seed(race, interaction.id))
            self.seed_tasks.add(task)
            task.add_done_callback(self.seed_tasks.discard)
        await self.voice_announcer.announce_player_joined(voice_client)
        confirmation = f"🏁 **{race.game}** lobby created in {channel.mention}."
        if interaction.response.is_done():
            await interaction.followup.send(confirmation, ephemeral=True)
        else:
            await interaction.response.send_message(confirmation, ephemeral=True)

    async def join_race(self, interaction: discord.Interaction) -> str:
        """Toggle the button-clicking user's membership in the tracker race."""
        race = self.service.get(interaction.channel_id or 0)
        if not race:
            return "There is no active race in this channel."
        joined = interaction.user.id not in race.entrants
        try:
            if joined:
                await self.rando_api.ensure_user(interaction.user.name, interaction.user.id)
                self.user_data.ensure_user(interaction.user.id)
                await self.rando_api.add_current_racer(interaction.user.name)
                self.service.join(race, interaction.user.id, interaction.user.display_name)
            else:
                await self.rando_api.remove_current_racer(interaction.user.name)
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
        """Validate and store one completed-race participant replay."""
        race = self.service.get(interaction.channel_id or 0)
        if not race:
            return "There is no race in this channel."
        if interaction.user.id not in race.entrants:
            return "Only players in this race can submit a replay."
        if race.status is not RaceStatus.COMPLETE:
            return "Replays can only be submitted after the race is finished."
        if replay.size > 100 * 1024:
            return "Replay files cannot exceed 100 KB."

        filename = Path(replay.filename).name
        if filename != replay.filename or Path(filename).suffix.casefold() != ".sotnr":
            return "Upload a valid `.sotnr` replay file."

        replay_directory = self.replays_directory / str(race.interaction_id)
        replay_path = replay_directory / filename
        if replay_path.exists():
            return "A replay with that filename has already been submitted for this race."

        replay_data = await replay.read()
        if len(replay_data) > 100 * 1024:
            return "Replay files cannot exceed 100 KB."
        replay_directory.mkdir(parents=True, exist_ok=True)
        replay_path.write_bytes(replay_data)
        race.replay_urls[interaction.user.id] = replay.url
        await self.race_message.update(race)
        return f"Replay submitted as `{filename}`."

    async def start_race(self, interaction: discord.Interaction, *, silent: bool = False) -> None:
        race = self.service.get(interaction.channel_id or 0)
        start_error = self.service.validate_start(race, interaction.user.id)
        if start_error:
            if start_error.startswith("Every racer") and interaction.guild and race:
                voice_client = interaction.guild.voice_client
                if (
                    voice_client
                    and voice_client.channel
                    and voice_client.channel.id == race.voice_channel_id
                ):
                    await self.voice_announcer.announce_ready_error(voice_client)
            if not silent:
                await interaction.response.send_message(start_error, ephemeral=True)
            else:
                await interaction.followup.send(start_error, ephemeral=True)
            return
        if not race:
            return
        race.countdown_in_progress = True
        race.countdown_starter_id = interaction.user.id
        await self.race_message.update(race)
        task = asyncio.create_task(self.run_countdown(race))
        self.countdown_tasks[race.interaction_id] = task
        task.add_done_callback(
            lambda completed, race_id=race.interaction_id: self.countdown_tasks.pop(race_id, None)
        )
        if not silent:
            await interaction.response.send_message("Race countdown started!")

    async def close_race(self, race: Race) -> str:
        """Close an active race and clean up its live Discord/API resources."""
        countdown_task = self.countdown_tasks.pop(race.interaction_id, None)
        if countdown_task:
            countdown_task.cancel()
        race.countdown_in_progress = False
        race.countdown_value = None
        race.countdown_starter_id = None
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

    async def record_finish(self, interaction: discord.Interaction) -> str | None:
        race = self.service.get(interaction.channel_id or 0)
        if not race:
            return "There is no active race in this channel."
        entrant = race.entrants.get(interaction.user.id)
        retrying_api = bool(
            entrant and entrant.finish_position is not None and not entrant.api_result_synced
        )
        retrying_completion = bool(
            entrant
            and entrant.finish_position is not None
            and entrant.api_result_synced
            and race.status is RaceStatus.COMPLETE
            and not race.api_race_finished
        )
        if not retrying_api and not retrying_completion:
            try:
                self.service.finish(race, interaction.user.id, interaction.user.display_name)
            except ValueError as error:
                return str(error)
            entrant = race.entrants[interaction.user.id]
        if not entrant.api_result_synced:
            try:
                await self.rando_api.finish_current_racer(
                    interaction.user.name,
                    finish_time_to_milliseconds(entrant.finish_time or "00:00:00.000"),
                    False,
                )
            except RandoApiError as error:
                logger.warning("Could not synchronize racer finish: %s", error)
                return f"Your finish was recorded locally, but API synchronization failed: {error}"
            entrant.mark_api_result_synced()
        elo_error = await self.update_elo_if_complete(race)
        await self.race_message.update(race)
        return elo_error

    async def record_forfeit(self, interaction: discord.Interaction) -> str | None:
        race = self.service.get(interaction.channel_id or 0)
        if not race:
            return "There is no active race in this channel."
        entrant = race.entrants.get(interaction.user.id)
        retrying_api = bool(entrant and entrant.forfeited and not entrant.api_result_synced)
        retrying_completion = bool(
            entrant
            and entrant.forfeited
            and entrant.api_result_synced
            and race.status is RaceStatus.COMPLETE
            and not race.api_race_finished
        )
        if not retrying_api and not retrying_completion:
            try:
                self.service.forfeit(race, interaction.user.id)
            except ValueError as error:
                return str(error)
            entrant = race.entrants[interaction.user.id]
        if not entrant.api_result_synced:
            try:
                await self.rando_api.finish_current_racer(interaction.user.name, None, True)
            except RandoApiError as error:
                logger.warning("Could not synchronize racer forfeit: %s", error)
                return f"Your forfeit was recorded locally, but API synchronization failed: {error}"
            entrant.mark_api_result_synced()
        elo_error = await self.update_elo_if_complete(race)
        await self.race_message.update(race)
        return elo_error

    async def update_elo_if_complete(self, race: Race) -> str | None:
        """Persist Elo once, then synchronize every new rating to the API."""
        if race.status is not RaceStatus.COMPLETE:
            return None
        if not all(entrant.api_result_synced for entrant in race.entrants.values()):
            return "Elo is waiting for every racer result to synchronize with the API."
        if not race.elo_processed:
            forfeited_placement = len(race.entrants)
            placements = {
                user_id: entrant.finish_position or forfeited_placement
                for user_id, entrant in race.entrants.items()
            }
            race.elo_changes = self.user_data.apply_race_elo(placements)
            race.elo_processed = True
        if not race.elo_api_synced:
            preset = next(
                (
                    value
                    for name, value in race.start_options.items()
                    if name.casefold() == "randomizer preset"
                ),
                None,
            )
            if not preset:
                return "Elo was saved locally, but the API update needs a randomizer preset."
            try:
                await asyncio.gather(
                    *(
                        self.rando_api.set_elo(user_id, preset, self.user_data.get_elo(user_id))
                        for user_id in race.entrants
                    )
                )
            except RandoApiError as error:
                logger.warning("Could not synchronize race Elo: %s", error)
                return f"Elo was saved locally, but API synchronization failed: {error}"
            race.elo_api_synced = True
        if not race.api_race_finished:
            try:
                await self.rando_api.finish_current_race()
            except RandoApiError as error:
                logger.warning("Could not finish current API race: %s", error)
                return f"Results and Elo were saved, but API race finalization failed: {error}"
            race.api_race_finished = True
        return None

    async def adjust_race_elo(self, race_id: int, ordered_user_ids: list[int]) -> str:
        """Replace a completed race's Elo result with an administrator-supplied order."""
        race = self.service.get_by_interaction_id(race_id)
        if not race:
            return f"I couldn't find race `{race_id}` in this bot session."
        if race.status is not RaceStatus.COMPLETE or not race.elo_processed:
            return "That race has not completed its Elo adjustment yet."
        if not ordered_user_ids:
            return "Supply every racer in finish order."
        if len(set(ordered_user_ids)) != len(ordered_user_ids):
            return "Each racer may only appear once."

        entrant_ids = set(race.entrants)
        supplied_ids = set(ordered_user_ids)
        if entrant_ids != supplied_ids:
            missing = entrant_ids - supplied_ids
            extra = supplied_ids - entrant_ids
            details = []
            if missing:
                details.append(
                    "missing " + ", ".join(f"<@{user_id}>" for user_id in sorted(missing))
                )
            if extra:
                details.append(
                    "not in race " + ", ".join(f"<@{user_id}>" for user_id in sorted(extra))
                )
            return "The order must contain every racer exactly once (" + "; ".join(details) + ")."

        try:
            new_changes = self.user_data.adjust_race_elo(race.elo_changes, ordered_user_ids)
        except (RuntimeError, ValueError) as error:
            return f"Elo adjustment failed: {error}"

        race.elo_changes = new_changes
        race.elo_api_synced = False
        preset = next(
            (
                value
                for name, value in race.start_options.items()
                if name.casefold() == "randomizer preset"
            ),
            None,
        )
        if preset:
            try:
                await asyncio.gather(
                    *(
                        self.rando_api.set_elo(user_id, preset, self.user_data.get_elo(user_id))
                        for user_id in ordered_user_ids
                    )
                )
            except RandoApiError as error:
                logger.warning("Could not synchronize adjusted race Elo: %s", error)
                await self.race_message.update(race)
                return f"Elo was adjusted locally, but API synchronization failed: {error}"
            race.elo_api_synced = True

        await self.race_message.update(race)
        order = " → ".join(f"<@{user_id}>" for user_id in ordered_user_ids)
        return f"Adjusted Elo for race `{race_id}` using this finish order: {order}."

    @commands.Cog.listener()
    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Play the error cue for unexpected slash-command failures."""
        logger.error("Application command failed: %s", error)
        race = self.service.get(interaction.channel_id or 0)
        if interaction.guild and race:
            voice_client = interaction.guild.voice_client
            if (
                voice_client
                and voice_client.channel
                and voice_client.channel.id == race.voice_channel_id
            ):
                await self.voice_announcer.announce_ready_error(voice_client)
        if not interaction.response.is_done():
            await interaction.response.send_message("Something went wrong.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    cog = RaceCog(
        bot,
        RaceService(),
        bot.seed_generator_command,
        UserDataService(
            Path.cwd() / "database" / "bot.sqlite3",
            Path.cwd() / "database" / "schema.sql",
        ),
        RandoApiClient(bot.settings.api_base_url, bot.settings.api_key),
    )
    await bot.add_cog(cog)
    await bot.add_cog(RaceCommands(cog, bot.start_options))
    bot.add_view(cog.join_view)
    bot.add_view(cog.running_view)
