"""Commands for creating, closing, and administering a race lobby."""

from enum import Enum

import discord
from discord import app_commands
from discord.ext import commands

from speedrun_race_bot.discord_ui.create_options import StartOption
from speedrun_race_bot.discord_ui.value_parsers import ASYNC_RACE_CLOSE_CHOICES
from speedrun_race_bot.domain import RaceStatus
from speedrun_race_bot.integrations.rando_api import RandoApiError
from speedrun_race_bot.race.coordinator import RaceCoordinator


class RaceCommands(commands.Cog):
    """The `/race` group and host-level lobby commands."""

    race = app_commands.Group(name="race", description="Manage speedrun races")

    def __init__(self, coordinator: RaceCoordinator, start_options: list[StartOption]) -> None:
        self.coordinator = coordinator
        self._register_create_command(start_options)
        self._register_async_command(start_options)

    def _register_create_command(self, start_options: list[StartOption]) -> None:
        """Build `/race create` with one enum parameter per YAML option group."""
        enum_namespace: dict[str, type[Enum]] = {}
        parameter_definitions = []
        selected_values = []
        for index, option in enumerate(start_options):
            enum_name = f"RaceOption{index}"
            enum_namespace[enum_name] = Enum(enum_name, {value: value for value in option.values})
            parameter_definitions.append(f"{option.parameter_name}: {enum_name} = None")
            selected_values.append(
                f"{option.name!r}: {option.parameter_name}.value "
                f"if {option.parameter_name} else None"
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
            "    await coordinator.create_race("
            "interaction, channel, voice_channel, annotation, selected_options)\n"
        )
        namespace: dict[str, object] = {
            "coordinator": self.coordinator,
            "discord": discord,
            **enum_namespace,
        }
        exec(source, namespace)  # noqa: S102 - options are trusted local YAML values
        self.race.remove_command("create")
        self.race.add_command(
            app_commands.Command(
                name="create",
                description="Create a speedrun race lobby",
                callback=namespace["create_callback"],
            )
        )

    def _register_async_command(self, start_options: list[StartOption]) -> None:
        """Build an immediately-running async race command from configured presets."""
        preset_option = next(
            (option for option in start_options if option.name.casefold() == "randomizer preset"),
            None,
        )
        if not preset_option:
            return

        async def async_callback(
            interaction: discord.Interaction, preset: str, closes_at: int
        ) -> None:
            await self.coordinator.create_async_race(interaction, preset, closes_at)

        async_callback = app_commands.describe(
            preset="Randomizer preset used for this race",
            closes_at="How long the async race remains open",
        )(async_callback)
        async_callback = app_commands.choices(
            preset=[app_commands.Choice(name=value, value=value) for value in preset_option.values],
            closes_at=[
                app_commands.Choice(name=label, value=seconds)
                for label, seconds in ASYNC_RACE_CLOSE_CHOICES
            ],
        )(async_callback)
        self.race.remove_command("async")
        self.race.add_command(
            app_commands.Command(
                name="async",
                description="Start an async race that reveals results at a deadline",
                callback=async_callback,
            )
        )

    @race.command(name="close", description="Close the current race")
    @app_commands.describe(async_race="Close the async race instead of the live race")
    async def close_race(self, interaction: discord.Interaction, async_race: bool = False) -> None:
        race = self.coordinator.service.get(interaction.channel_id or 0, is_async=async_race)
        if not race and not async_race:
            race = self.coordinator.service.get(interaction.channel_id or 0, is_async=True)
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
        result = await self.coordinator.close_race(race)
        await interaction.followup.send(result, ephemeral=True)

    @app_commands.command(name="playerkick", description="Remove a player from the race lobby")
    async def player_kick(self, interaction: discord.Interaction, player: discord.Member) -> None:
        race = self.coordinator.service.get(interaction.channel_id or 0, is_async=False)
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
            entrant = race.entrants[player.id]
            await self.coordinator.rando_api.remove_current_racer(entrant.api_name or player.name)
            self.coordinator.service.leave(race, player.id)
        except (RandoApiError, ValueError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await self.coordinator.race_message.update(race)
        await interaction.response.send_message(
            f"Removed {player.mention} from the race.", ephemeral=True
        )
