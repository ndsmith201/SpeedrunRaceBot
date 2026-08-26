"""Persistent Discord views used by race tracker messages."""

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from speedrun_race_bot.cogs.races import RaceCog


class JoinRaceView(discord.ui.View):
    """Persistent controls attached to every race-lobby tracker."""

    def __init__(self, cog: "RaceCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Join", style=discord.ButtonStyle.primary, custom_id="speedrun-race:join"
    )
    async def join_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        message = await self.cog.join_race(interaction)
        if message not in {"You joined the race!", "You left the race."}:
            await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(
        label="Ready", style=discord.ButtonStyle.primary, custom_id="speedrun-race:ready"
    )
    async def ready_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        message = await self.cog.ready_racer(interaction)
        if message not in {"You are marked ready!", "You are no longer ready."}:
            await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(
        label="Start Race", style=discord.ButtonStyle.success, custom_id="speedrun-race:start"
    )
    async def start_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        await self.cog.start_race(interaction, silent=True)


class RunningRaceView(discord.ui.View):
    """Persistent controls shown while a race is in progress."""

    def __init__(self, cog: "RaceCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Finish", style=discord.ButtonStyle.success, custom_id="speedrun-race:finish"
    )
    async def finish_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        error = await self.cog.record_finish(interaction)
        if error:
            await interaction.followup.send(error, ephemeral=True)

    @discord.ui.button(
        label="Forfeit", style=discord.ButtonStyle.danger, custom_id="speedrun-race:forfeit"
    )
    async def forfeit_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        error = await self.cog.record_forfeit(interaction)
        if error:
            await interaction.followup.send(error, ephemeral=True)
