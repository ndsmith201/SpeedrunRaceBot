"""Discord slash-command definitions for the race bot."""

import asyncio
import re
import shutil
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from speedrun_race_bot.helpers import is_country_flag_emoji, normalize_twitch_url
from speedrun_race_bot.models import RaceStatus
from speedrun_race_bot.race_options import StartOption
from speedrun_race_bot.services.rando_api import RandoApiError

if TYPE_CHECKING:
    from speedrun_race_bot.cogs.races import RaceCog


class RaceCommands(commands.Cog):
    """Slash commands that delegate race operations to RaceCog."""

    race = app_commands.Group(name="race", description="Manage speedrun races")

    def __init__(self, race_cog: "RaceCog", start_options: list[StartOption]) -> None:
        self.race_cog = race_cog
        self.start_options = start_options
        self._register_create_command()

    def _register_create_command(self) -> None:
        """Build `/race create` with one enum parameter per YAML option group."""
        enum_namespace: dict[str, type[Enum]] = {}
        parameter_definitions = []
        selected_values = []
        for index, option in enumerate(self.start_options):
            enum_name = f"RaceOption{index}"
            enum_namespace[enum_name] = Enum(enum_name, {value: value for value in option.values})
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
            "    await command_cog.race_cog.create_race("
            "interaction, channel, voice_channel, annotation, selected_options)\n"
        )
        namespace: dict[str, object] = {
            "command_cog": self,
            "discord": discord,
            **enum_namespace,
        }
        exec(source, namespace)
        self.race.add_command(
            app_commands.Command(
                name="create",
                description="Create a speedrun race lobby",
                callback=namespace["create_callback"],
            )
        )

    @race.command(name="close", description="Close the current race")
    async def close_race(self, interaction: discord.Interaction) -> None:
        race = self.race_cog.service.get(interaction.channel_id or 0)
        if not race:
            await interaction.response.send_message(
                "There is no active race in this channel.", ephemeral=True
            )
            return
        is_administrator = isinstance(interaction.user, discord.Member) and (
            interaction.user.guild_permissions.administrator
        )
        if interaction.user.id != race.host_id and not is_administrator:
            await interaction.response.send_message(
                "Only the race host or a server administrator can close the race.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        result = await self.race_cog.close_race(race)
        await interaction.followup.send(result, ephemeral=True)

    @app_commands.command(name="flag", description="Save the flag shown next to your race name")
    async def flag(self, interaction: discord.Interaction, emoji: str) -> None:
        emoji = emoji.strip()
        if not is_country_flag_emoji(emoji):
            await interaction.response.send_message(
                "Choose a Discord country flag emoji, such as 🇺🇸 or 🇯🇵.", ephemeral=True
            )
            return
        self.race_cog.user_data.set_flag(interaction.user.id, emoji)
        race = self.race_cog.service.get(interaction.channel_id or 0)
        if race and interaction.user.id in race.entrants:
            await self.race_cog.race_message.update(race)
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
        self.race_cog.user_data.set_stream_url(interaction.user.id, stream_url)
        race = self.race_cog.service.get(interaction.channel_id or 0)
        if race and interaction.user.id in race.entrants:
            await self.race_cog.race_message.update(race)
        await interaction.response.send_message(
            f"Saved your Twitch stream: {stream_url}", ephemeral=True
        )

    @app_commands.command(name="replay", description="Submit your finished-race replay")
    @app_commands.describe(replay="Your .sotnr replay file (maximum 100 KB)")
    async def replay(self, interaction: discord.Interaction, replay: discord.Attachment) -> None:
        await interaction.response.defer(ephemeral=True)
        result = await self.race_cog.save_replay(interaction, replay)
        await interaction.followup.send(result, ephemeral=True)

    @app_commands.command(name="replays", description="Download a race's submitted replays")
    @app_commands.describe(raceid="The race creation interaction ID")
    async def replays(self, interaction: discord.Interaction, raceid: str) -> None:
        await interaction.response.defer(ephemeral=True)
        race_id = raceid.strip()
        if not race_id.isdecimal():
            await interaction.followup.send("Enter a valid numeric race ID.", ephemeral=True)
            return

        replays_root = self.race_cog.replays_directory.resolve()
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
            replay_archive = discord.File(
                archive_path,
                filename=f"replays-{race_id}.zip",
            )
            try:
                await interaction.followup.send(file=replay_archive, ephemeral=True)
            finally:
                replay_archive.close()

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
        result = await self.race_cog.adjust_race_elo(int(race_id), player_ids)
        await interaction.followup.send(result, ephemeral=True)

    @app_commands.command(
        name="newseason", description="Back up user data and reset every Elo rating"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def new_season(self, interaction: discord.Interaction) -> None:
        backup_path = self.race_cog.user_data.start_new_season(Path.cwd() / "database" / "backups")
        await interaction.response.send_message(
            f"New season started. Elo ratings were reset to 1200. Backup: `{backup_path.name}`",
            ephemeral=True,
        )

    @app_commands.command(name="playerkick", description="Remove a player from the race lobby")
    async def player_kick(self, interaction: discord.Interaction, player: discord.Member) -> None:
        race = self.race_cog.service.get(interaction.channel_id or 0)
        if not race:
            await interaction.response.send_message(
                "There is no active race in this channel.", ephemeral=True
            )
            return
        if race.status is not RaceStatus.LOBBY:
            await interaction.response.send_message(
                "Players can only be removed before the race starts.", ephemeral=True
            )
            return
        is_administrator = isinstance(interaction.user, discord.Member) and (
            interaction.user.guild_permissions.administrator
        )
        if interaction.user.id != race.host_id and not is_administrator:
            await interaction.response.send_message(
                "Only the race host or a server administrator can remove players.",
                ephemeral=True,
            )
            return
        if player.id not in race.entrants:
            await interaction.response.send_message(
                f"{player.mention} is not in this race.", ephemeral=True
            )
            return
        try:
            await self.race_cog.rando_api.remove_current_racer(player.name)
            self.race_cog.service.leave(race, player.id)
        except (RandoApiError, ValueError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await self.race_cog.race_message.update(race)
        await interaction.response.send_message(
            f"Removed {player.mention} from the race.", ephemeral=True
        )
