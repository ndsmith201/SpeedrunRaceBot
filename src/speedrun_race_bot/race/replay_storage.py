"""Validation and local storage for submitted race replay files."""

from pathlib import Path

import discord

from speedrun_race_bot.discord_ui.race_tracker import RaceTracker
from speedrun_race_bot.domain import RaceStatus
from speedrun_race_bot.race.state import RaceState

MAX_REPLAY_BYTES = 100 * 1024


class ReplayStorage:
    def __init__(self, races: RaceState, tracker: RaceTracker, directory: Path) -> None:
        self.races = races
        self.tracker = tracker
        self.directory = directory

    async def save(self, interaction: discord.Interaction, replay: discord.Attachment) -> str:
        race = self.races.get(interaction.channel_id or 0, is_async=False)
        if not race:
            return "There is no race in this channel."
        if interaction.user.id not in race.entrants:
            return "Only players in this race can submit a replay."
        if race.status is not RaceStatus.COMPLETE:
            return "Replays can only be submitted after the race is finished."
        if replay.size > MAX_REPLAY_BYTES:
            return "Replay files cannot exceed 100 KB."

        filename = Path(replay.filename).name
        if filename != replay.filename or Path(filename).suffix.casefold() != ".sotnr":
            return "Upload a valid `.sotnr` replay file."

        replay_directory = self.directory / str(race.interaction_id)
        replay_path = replay_directory / filename
        if replay_path.exists():
            return "A replay with that filename has already been submitted for this race."

        replay_data = await replay.read()
        if len(replay_data) > MAX_REPLAY_BYTES:
            return "Replay files cannot exceed 100 KB."
        replay_directory.mkdir(parents=True, exist_ok=True)
        replay_path.write_bytes(replay_data)
        race.replay_urls[interaction.user.id] = replay.url
        self.races.save(race)
        await self.tracker.update(race)
        return f"Replay submitted as `{filename}`."
