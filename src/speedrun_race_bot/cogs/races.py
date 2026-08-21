import asyncio
from enum import Enum

import discord
from discord import app_commands
from discord.ext import commands
from importlib.resources import files
import logging
from pathlib import Path
import re

from speedrun_race_bot.models import Race, RaceStatus
from speedrun_race_bot.race_options import StartOption
from speedrun_race_bot.seed_generation import run_seed_command
from speedrun_race_bot.services.races import RaceService
from speedrun_race_bot.services.user_flags import UserFlagService
from speedrun_race_bot.services.voice import VoiceAnnouncer

logger = logging.getLogger(__name__)


def is_country_flag_emoji(value: str) -> bool:
    """Return whether a value is a two-regional-indicator country flag."""
    return len(value) == 2 and all("\U0001F1E6" <= character <= "\U0001F1FF" for character in value)


class RaceCog(commands.Cog):
    race = app_commands.Group(name="race", description="Manage speedrun races")

    def __init__(
        self,
        bot: commands.Bot,
        service: RaceService,
        seed_generator_command: str | None,
        start_options: list[StartOption],
        user_flags: UserFlagService,
    ) -> None:
        self.bot = bot
        self.service = service
        self.seed_generator_command = seed_generator_command
        self.start_options = start_options
        self.user_flags = user_flags
        self.project_directory = Path.cwd()
        self.seeds_directory = self.project_directory / "seeds"
        self.join_view = JoinRaceView(self)
        self.running_view = RunningRaceView(self)
        self.voice_announcer = VoiceAnnouncer()
        self.seed_tasks: set[asyncio.Task[None]] = set()
        self.countdown_tasks: set[asyncio.Task[None]] = set()
        self._register_create_command()

    def _register_create_command(self) -> None:
        """Build `/race create` with one enum parameter per YAML option group."""
        enum_namespace: dict[str, type[Enum]] = {}
        parameter_definitions = []
        selected_values = []
        for index, option in enumerate(self.start_options):
            enum_name = f"RaceOption{index}"
            enum_namespace[enum_name] = Enum(
                enum_name, {value: value for value in option.values}
            )
            parameter_definitions.append(f"{option.parameter_name}: {enum_name} = None")
            selected_values.append(
                f"{option.name!r}: {option.parameter_name}.value if {option.parameter_name} else None"
            )
        parameters = ", ".join(
            [
                "interaction: discord.Interaction",
                "channel: discord.TextChannel",
                "voice_channel: discord.VoiceChannel",
                "annotation: str = None",
                *parameter_definitions,
            ]
        )
        source = (
            f"async def create_callback({parameters}):\n"
            f"    selected_options = {{{', '.join(selected_values)}}}\n"
            "    await cog.create_race(interaction, channel, voice_channel, annotation, selected_options)\n"
        )
        namespace: dict[str, object] = {"cog": self, "discord": discord, **enum_namespace}
        exec(source, namespace)
        callback = namespace["create_callback"]
        self.race.add_command(
            app_commands.Command(
                name="create", description="Create a speedrun race lobby", callback=callback
            )
        )

    def tracker_markdown(self, race: Race) -> str:
        status_emojis = {
            RaceStatus.LOBBY: "⏳",
            RaceStatus.RUNNING: "🏁",
            RaceStatus.COMPLETE: "✅",
        }
        countdown_emojis = {3: "🔴", 2: "🔵", 1: "🟡"}
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        template = files("speedrun_race_bot.templates").joinpath("race_tracker.md").read_text(
            encoding="utf-8"
        )
        sections = dict(re.findall(r"<!-- section: (\w+) -->\n(.*?)<!-- endsection -->", template, re.DOTALL))
        template = re.sub(r"<!-- section: \w+ -->\n.*?<!-- endsection -->\n*", "", template, flags=re.DOTALL)

        def render_section(section_name: str, **values: str) -> str:
            return sections[section_name].format(**values).rstrip("\n")

        racers = []
        ordered_entrants = sorted(
            race.entrants.values(),
            key=lambda entrant: (
                0 if entrant.finish_time else 2 if entrant.forfeited else 1,
                entrant.finish_time or "",
            ),
        )
        for entrant in ordered_entrants:
            medal = f"{medals.get(entrant.finish_position, '')} " if entrant.finish_position else ""
            forfeit_marker = "💩 " if entrant.forfeited else ""
            if race.status is RaceStatus.LOBBY:
                time_or_status = "✅ Ready" if entrant.is_ready else "⏳ Not ready"
            elif entrant.forfeited:
                time_or_status = "Forfeit"
            else:
                time_or_status = entrant.finish_time or "Running"
            flag = self.user_flags.get(entrant.user_id)
            flag_prefix = f"{flag} " if flag else ""
            racers.append(
                render_section(
                    "racer",
                    result_marker=f"{medal}{forfeit_marker}",
                    flag=flag_prefix,
                    name=entrant.display_name,
                    result=time_or_status,
                )
            )
        racer_list = "\n".join(racers) or render_section("no_racers")
        if race.seed_filename:
            seed_line = render_section("seed_link", filename=race.seed_filename, url=race.seed_url or "")
        elif race.seed_generation_in_progress:
            guild = self.bot.get_guild(race.guild_id)
            walk_cycle = discord.utils.get(guild.emojis, name="alycardwalkcycle") if guild else None
            seed_line = render_section("seed_emoji", emoji=str(walk_cycle or ":alycardwalkcycle:"))
        elif race.seed_generation_error:
            seed_line = render_section("seed_error")
        else:
            seed_line = ""
        randomizer_preset = next(
            (
                value
                for name, value in race.start_options.items()
                if name.casefold() == "randomizer preset"
            ),
            None,
        )
        status_emoji = countdown_emojis.get(race.countdown_value) or (
            "🟢" if race.show_go_emoji else status_emojis[race.status]
        )
        return template.format(
            game=race.game,
            annotation_line=(
                render_section("annotation", annotation=race.annotation) if race.annotation else ""
            ),
            title_prefix=f"{status_emoji} " if status_emoji else "",
            randomizer_preset_line=(
                render_section("randomizer_preset", value=randomizer_preset)
                if randomizer_preset
                else ""
            ),
            seed_line=seed_line,
            racers=racer_list,
        ).strip()

    def tracker_embed(self, race: Race) -> discord.Embed:
        """Build the live tracker panel with a status-specific accent stripe."""
        status_colors = {
            RaceStatus.LOBBY: discord.Color.yellow(),
            RaceStatus.RUNNING: discord.Color.green(),
            RaceStatus.COMPLETE: discord.Color.light_grey(),
        }
        embed = discord.Embed(
            description=self.tracker_markdown(race),
            color=status_colors[race.status],
        )
        return embed

    async def update_tracker(self, race: Race) -> None:
        """Edit the persistent race tracker after each state change."""
        channel = self.bot.get_channel(race.channel_id)
        if not isinstance(channel, discord.TextChannel) or not race.status_message_id:
            return
        try:
            message = await channel.fetch_message(race.status_message_id)
            await message.edit(
                content=None,
                embed=self.tracker_embed(race),
                view=(
                    self.join_view
                    if race.status is RaceStatus.LOBBY and not race.countdown_in_progress
                    else self.running_view if race.status is RaceStatus.RUNNING else None
                ),
            )
        except discord.HTTPException:
            # The next command still succeeds if a moderator deleted the tracker.
            return

    async def generate_and_attach_seed(self, race: Race) -> None:
        """Generate the seed without delaying creation of the race lobby."""
        try:
            seed_path = await run_seed_command(
                self.seed_generator_command or "",
                race,
                self.project_directory,
                self.seeds_directory,
            )
            race.seed_filename = seed_path.name
            race.seed_generation_in_progress = False

            channel = self.bot.get_channel(race.channel_id)
            if isinstance(channel, discord.TextChannel) and race.status_message_id:
                seed_message = await channel.send(file=discord.File(seed_path, filename=seed_path.name))
                race.seed_url = seed_message.attachments[0].url
                await self.update_tracker(race)
            seed_path.unlink()
        except Exception:
            race.seed_generation_in_progress = False
            race.seed_generation_error = True
            logger.exception("Seed generation command failed for %s — %s", race.game, race.category)
            await self.update_tracker(race)

    async def run_countdown(self, race: Race) -> None:
        """Show the three countdown thumbnails, then begin the race timer on Go."""
        try:
            channel = self.bot.get_channel(race.channel_id)
            if not isinstance(channel, discord.TextChannel) or not race.status_message_id:
                return
            guild = self.bot.get_guild(race.guild_id)
            voice_client = guild.voice_client if guild else None
            if voice_client and voice_client.channel and voice_client.channel.id == race.voice_channel_id:
                await self.voice_announcer.announce_random_countdown(voice_client)
            for count in (3, 2, 1):
                race.countdown_value = count
                await self.update_tracker(race)
                await asyncio.sleep(0.8)
            race.countdown_value = None
            race.countdown_in_progress = False
            self.service.start(race, race.countdown_starter_id or race.host_id)
            race.countdown_starter_id = None
            race.show_go_emoji = True
            await self.update_tracker(race)
            await asyncio.sleep(0.8)
            race.show_go_emoji = False
            await self.update_tracker(race)
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()
        except Exception:
            race.countdown_in_progress = False
            race.countdown_value = None
            race.countdown_starter_id = None
            logger.exception("Could not complete countdown for %s", race.game)
            await self.update_tracker(race)

    async def create_race(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        voice_channel: discord.VoiceChannel,
        annotation: str | None,
        selected_options: dict[str, str | None],
    ) -> None:
        if not interaction.guild or not interaction.guild_id:
            await interaction.response.send_message("Races can only be created in a server channel.", ephemeral=True)
            return
        if channel.guild.id != interaction.guild_id or voice_channel.guild.id != interaction.guild_id:
            await interaction.response.send_message("Choose channels from this server.", ephemeral=True)
            return
        existing_race = self.service.get(channel.id)
        if existing_race and existing_race.status is not RaceStatus.COMPLETE:
            await interaction.response.send_message(
                "This channel already has an active race.", ephemeral=True
            )
            return
        try:
            voice_client = interaction.guild.voice_client
            if voice_client and voice_client.is_connected():
                await voice_client.move_to(voice_channel)
            else:
                voice_client = await voice_channel.connect()
        except (discord.ClientException, discord.HTTPException) as error:
            await interaction.response.send_message(
                f"I could not join {voice_channel.mention}: {error}", ephemeral=True
            )
            return
        race = Race(
            interaction.guild_id,
            channel.id,
            voice_channel.id,
            interaction.user.id,
            self.bot.settings.race_game,
            "",
            annotation.strip() if annotation else None,
        )
        race.start_options = {
            name: value for name, value in selected_options.items() if value is not None
        }
        if self.seed_generator_command:
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
        tracker = await channel.send(embed=self.tracker_embed(race), view=self.join_view)
        race.status_message_id = tracker.id
        if self.seed_generator_command:
            task = asyncio.create_task(self.generate_and_attach_seed(race))
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
                self.service.join(race, interaction.user.id, interaction.user.display_name)
            else:
                self.service.leave(race, interaction.user.id)
        except ValueError as error:
            return str(error)
        await self.update_tracker(race)
        if joined and interaction.guild:
            voice_client = interaction.guild.voice_client
            if voice_client and voice_client.channel and voice_client.channel.id == race.voice_channel_id:
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
        await self.update_tracker(race)
        return "You are marked ready!" if is_ready else "You are no longer ready."

    @race.command(name="start", description="Start the active race (host only)")
    async def start(self, interaction: discord.Interaction) -> None:
        await self.start_race(interaction)

    async def start_race(self, interaction: discord.Interaction, *, silent: bool = False) -> None:
        race = self.service.get(interaction.channel_id or 0)
        if not race:
            if not silent:
                await interaction.response.send_message("There is no active race in this channel.", ephemeral=True)
            else:
                await interaction.followup.send("There is no active race in this channel.", ephemeral=True)
            return
        if interaction.user.id not in race.entrants:
            if not silent:
                await interaction.response.send_message(
                    "Only race participants can start this race.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Only race participants can start this race.", ephemeral=True
                )
            return
        if race.status is not RaceStatus.LOBBY:
            if not silent:
                await interaction.response.send_message("This race cannot be started now.", ephemeral=True)
            else:
                await interaction.followup.send("This race cannot be started now.", ephemeral=True)
            return
        if race.countdown_in_progress:
            if not silent:
                await interaction.response.send_message("The race countdown is already running.", ephemeral=True)
            else:
                await interaction.followup.send("The race countdown is already running.", ephemeral=True)
            return
        if not race.entrants or not all(entrant.is_ready for entrant in race.entrants.values()):
            if interaction.guild:
                voice_client = interaction.guild.voice_client
                if voice_client and voice_client.channel and voice_client.channel.id == race.voice_channel_id:
                    await self.voice_announcer.announce_ready_error(voice_client)
            if not silent:
                await interaction.response.send_message(
                    "Every racer must click **Ready** before the race can start.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Every racer must click **Ready** before the race can start.", ephemeral=True
                )
            return
        if race.seed_generation_in_progress:
            if not silent:
                await interaction.response.send_message(
                    "The race seed is still being generated.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "The race seed is still being generated.", ephemeral=True
                )
            return
        if race.seed_generation_error:
            if not silent:
                await interaction.response.send_message(
                    "The race seed could not be generated, so this race cannot start.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "The race seed could not be generated, so this race cannot start.", ephemeral=True
                )
            return
        race.countdown_in_progress = True
        race.countdown_starter_id = interaction.user.id
        await self.update_tracker(race)
        task = asyncio.create_task(self.run_countdown(race))
        self.countdown_tasks.add(task)
        task.add_done_callback(self.countdown_tasks.discard)
        if not silent:
            await interaction.response.send_message("Race countdown started!")

    @race.command(name="finish", description="Record your finish time")
    async def finish(self, interaction: discord.Interaction) -> None:
        error = await self.record_finish(interaction)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        race = self.service.get(interaction.channel_id or 0)
        finish_time = race.entrants[interaction.user.id].finish_time if race else None
        await interaction.response.send_message(
            f"✅ {interaction.user.mention} finished in **{finish_time}**!"
        )

    async def record_finish(self, interaction: discord.Interaction) -> str | None:
        race = self.service.get(interaction.channel_id or 0)
        if not race:
            return "There is no active race in this channel."
        try:
            self.service.finish(race, interaction.user.id, interaction.user.display_name)
        except ValueError as error:
            return str(error)
        await self.update_tracker(race)
        return None

    async def record_forfeit(self, interaction: discord.Interaction) -> str | None:
        race = self.service.get(interaction.channel_id or 0)
        if not race:
            return "There is no active race in this channel."
        try:
            self.service.forfeit(race, interaction.user.id)
        except ValueError as error:
            return str(error)
        await self.update_tracker(race)
        return None

    @commands.Cog.listener()
    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Play the error cue for unexpected slash-command failures."""
        logger.error("Application command failed: %s", error)
        race = self.service.get(interaction.channel_id or 0)
        if interaction.guild and race:
            voice_client = interaction.guild.voice_client
            if voice_client and voice_client.channel and voice_client.channel.id == race.voice_channel_id:
                await self.voice_announcer.announce_ready_error(voice_client)
        if not interaction.response.is_done():
            await interaction.response.send_message("Something went wrong.", ephemeral=True)

    @app_commands.command(name="flag", description="Save the flag shown next to your race name")
    async def flag(self, interaction: discord.Interaction, emoji: str) -> None:
        emoji = emoji.strip()
        if not is_country_flag_emoji(emoji):
            await interaction.response.send_message(
                "Choose a Discord country flag emoji, such as 🇺🇸 or 🇯🇵.", ephemeral=True
            )
            return
        self.user_flags.set(interaction.user.id, emoji)
        race = self.service.get(interaction.channel_id or 0)
        if race and interaction.user.id in race.entrants:
            await self.update_tracker(race)
        await interaction.response.send_message(f"Saved your flag as {emoji}.", ephemeral=True)

    @race.command(name="status", description="Show the active race status")
    async def status(self, interaction: discord.Interaction) -> None:
        race = self.service.get(interaction.channel_id or 0)
        if not race:
            await interaction.response.send_message("There is no active race in this channel.", ephemeral=True)
            return
        await interaction.response.send_message(embed=self.tracker_embed(race))


class JoinRaceView(discord.ui.View):
    """Persistent button attached to every race-lobby tracker."""

    def __init__(self, cog: RaceCog) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Join", style=discord.ButtonStyle.primary, custom_id="speedrun-race:join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        message = await self.cog.join_race(interaction)
        if message not in {"You joined the race!", "You left the race."}:
            await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(label="Ready", style=discord.ButtonStyle.primary, custom_id="speedrun-race:ready")
    async def ready_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        message = await self.cog.ready_racer(interaction)
        if message not in {"You are marked ready!", "You are no longer ready."}:
            await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(
        label="Start Race", style=discord.ButtonStyle.success, custom_id="speedrun-race:start"
    )
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self.cog.start_race(interaction, silent=True)


class RunningRaceView(discord.ui.View):
    """Controls shown while a race is in progress."""

    def __init__(self, cog: RaceCog) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Finish", style=discord.ButtonStyle.success, custom_id="speedrun-race:finish")
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        error = await self.cog.record_finish(interaction)
        if error:
            await interaction.followup.send(error, ephemeral=True)

    @discord.ui.button(label="Forfeit", style=discord.ButtonStyle.danger, custom_id="speedrun-race:forfeit")
    async def forfeit_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        error = await self.cog.record_forfeit(interaction)
        if error:
            await interaction.followup.send(error, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    cog = RaceCog(
        bot,
        RaceService(),
        bot.seed_generator_command,
        bot.start_options,
        UserFlagService(Path.cwd() / "data" / "user_flags.json"),
    )
    await bot.add_cog(cog)
    bot.add_view(cog.join_view)
    bot.add_view(cog.running_view)
