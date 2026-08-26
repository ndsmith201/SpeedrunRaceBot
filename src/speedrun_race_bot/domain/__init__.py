"""Core race entities with no Discord or persistence dependencies."""

from speedrun_race_bot.domain.player import Player
from speedrun_race_bot.domain.race import Race, RaceStatus

__all__ = ["Player", "Race", "RaceStatus"]
