"""Rendering and updates for the persistent race tracker message."""

import discord
from discord.ext import commands

from speedrun_race_bot.discord_ui.controls import AsyncRaceView, JoinRaceView, RunningRaceView
from speedrun_race_bot.discord_ui.tracker_template import load_tracker_template
from speedrun_race_bot.domain import Race, RaceStatus
from speedrun_race_bot.persistence import UserRepository


class RaceTracker:
    def __init__(
        self,
        bot: commands.Bot,
        user_data: UserRepository,
        join_view: JoinRaceView,
        running_view: RunningRaceView,
        async_view: AsyncRaceView | None = None,
    ) -> None:
        self.bot = bot
        self.user_data = user_data
        self.join_view = join_view
        self.running_view = running_view
        self.async_view = async_view
        self.template = load_tracker_template()

    def markdown(self, race: Race) -> str:
        status_emojis = {
            RaceStatus.LOBBY: "⏳",
            RaceStatus.RUNNING: "🏁",
            RaceStatus.COMPLETE: "✅",
        }
        countdown_emojis = {3: "🔴", 2: "🔵", 1: "🟡"}
        render_section = self.template.section

        guild = self.bot.get_guild(race.guild_id)
        racer_list = "" if race.entrants else render_section("no_racers")
        if race.seed_filename:
            seed_line = render_section(
                "seed_link", filename=race.seed_filename, url=race.seed_url or ""
            )
        elif race.seed_generation_in_progress:
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
        status_emoji = (
            "⛔"
            if race.closed and race.status is not RaceStatus.COMPLETE
            else countdown_emojis.get(race.countdown_value)
            or ("🟢" if race.show_go_emoji else status_emojis[race.status])
        )
        async_close_line = ""
        if race.async_closes_at:
            close_timestamp = int(race.async_closes_at.timestamp())
            async_close_line = render_section(
                "async_closes",
                absolute=f"<t:{close_timestamp}:F>",
                relative=f"<t:{close_timestamp}:R>",
            )
        if race.is_async:
            instructions = render_section(
                "async_complete_instructions"
                if race.status is RaceStatus.COMPLETE or race.closed
                else "async_running_instructions"
            )
        else:
            instructions = render_section("standard_instructions")
        return self.template.body.format(
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
            race_id_line=render_section("race_id", value=str(race.interaction_id)),
            async_close_line=async_close_line,
            seed_line=seed_line,
            feedback_line=render_section("feedback_link"),
            racers=racer_list,
            instructions=instructions,
        ).strip()

    def embed(self, race: Race) -> discord.Embed:
        status_colors = {
            RaceStatus.LOBBY: discord.Color.yellow(),
            RaceStatus.RUNNING: discord.Color.green(),
            RaceStatus.COMPLETE: discord.Color.light_grey(),
        }
        markdown = self.markdown(race)
        description, marker, content_after_players = markdown.partition("<!-- player-columns -->")
        embed = discord.Embed(description=description.strip(), color=status_colors[race.status])
        if race.entrants:
            player_columns = self.player_columns(race)
            for name, value in player_columns:
                embed.add_field(name=name, value=value, inline=len(player_columns) > 1)
        if marker and content_after_players.strip():
            embed.add_field(name="\u200b", value=content_after_players.strip(), inline=False)
        return embed

    def player_columns(self, race: Race) -> list[tuple[str, str]]:
        """Render the racer, result, Elo, and tags columns."""
        render_section = self.template.section

        racers: list[str] = []
        results: list[str] = []
        elo_ratings: list[str] = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        guild = self.bot.get_guild(race.guild_id)
        twitch_emoji = discord.utils.get(guild.emojis, name="twitch") if guild else None
        vhs_emoji = discord.utils.get(guild.emojis, name="vhs") if guild else None
        ordered_entrants = list(race.entrants.values())
        if not race.results_hidden:
            ordered_entrants.sort(
                key=lambda entrant: (
                    0 if entrant.finish_time else 2 if entrant.forfeited else 1,
                    entrant.finish_time or "",
                )
            )
        for entrant in ordered_entrants:
            if race.results_hidden:
                result = "Hidden until close"
            elif race.status is RaceStatus.LOBBY:
                result = "✅" if entrant.is_ready else "⏳"
            elif entrant.forfeited:
                result = "Forfeit"
            else:
                result = entrant.finish_time or "Running"
            replay_url = race.replay_urls.get(entrant.user_id)
            if replay_url and not race.results_hidden:
                result += render_section(
                    "player_replay",
                    emoji=str(vhs_emoji or "📼"),
                    url=replay_url,
                )
            elo_change = race.elo_changes.get(entrant.user_id)
            elo_delta_text = ""
            if race.elo_processed and elo_change and not race.results_hidden:
                signed_change = f"+{elo_change}" if elo_change > 0 else str(elo_change)
                elo_delta_text = render_section("elo_delta", change=signed_change)
            flag = self.user_data.get_flag(entrant.user_id)
            stream_url = self.user_data.get_stream_url(entrant.user_id)
            entrant_tags = []
            if flag:
                entrant_tags.append(render_section("player_flag", flag=flag))
            if stream_url:
                entrant_tags.append(
                    render_section(
                        "player_stream",
                        emoji=str(twitch_emoji or ":twitch:"),
                        url=stream_url,
                    )
                )
            entrant_tags_text = " ".join(entrant_tags)
            racers.append(
                render_section(
                    "player_racer",
                    result_marker=(
                        ""
                        if race.results_hidden
                        else f"{medals.get(entrant.finish_position, '')} "
                        if entrant.finish_position
                        else "🪦 "
                        if entrant.forfeited
                        else ""
                    ),
                    name=entrant.display_name,
                    tags=f"{entrant_tags_text} " if entrant_tags_text else "",
                )
            )
            results.append(render_section("player_result", result=result))
            elo_ratings.append(
                render_section(
                    "player_elo",
                    elo=str(self.user_data.get_elo(entrant.user_id)),
                    elo_delta=elo_delta_text,
                )
            )
        return [
            (render_section("column_racer_title"), "\n".join(racers)),
            (
                render_section(
                    "column_ready_title"
                    if race.status is RaceStatus.LOBBY
                    else "column_result_title"
                ),
                "\n".join(results),
            ),
            (render_section("column_elo_title"), "\n".join(elo_ratings)),
        ]

    async def create(self, race: Race, channel: discord.TextChannel) -> discord.Message:
        """Publish the persistent tracker and save its Discord message ID."""
        message = await channel.send(embed=self.embed(race), view=self._view_for(race))
        race.status_message_id = message.id
        return message

    async def update(self, race: Race) -> None:
        """Edit the persistent race tracker after a state change."""
        channel = self.bot.get_channel(race.channel_id)
        if not isinstance(channel, discord.TextChannel) or not race.status_message_id:
            return
        try:
            message = await channel.fetch_message(race.status_message_id)
            await message.edit(
                content=None,
                embed=self.embed(race),
                view=self._view_for(race),
            )
        except discord.HTTPException:
            return

    def _view_for(self, race: Race) -> discord.ui.View | None:
        if race.closed:
            return None
        if race.is_async and race.status is RaceStatus.RUNNING:
            return self.async_view
        if race.status is RaceStatus.LOBBY and not race.countdown_in_progress:
            return self.join_view
        if race.status is RaceStatus.RUNNING:
            return self.running_view
        return None
