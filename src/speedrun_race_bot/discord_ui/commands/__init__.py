"""Slash-command cogs grouped by user-facing responsibility."""

from speedrun_race_bot.discord_ui.commands.admin import AdminCommands
from speedrun_race_bot.discord_ui.commands.player_profile import PlayerProfileCommands
from speedrun_race_bot.discord_ui.commands.race import RaceCommands
from speedrun_race_bot.discord_ui.commands.replays import ReplayCommands

__all__ = ["AdminCommands", "PlayerProfileCommands", "RaceCommands", "ReplayCommands"]
