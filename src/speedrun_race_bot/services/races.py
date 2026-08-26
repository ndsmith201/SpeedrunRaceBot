from datetime import datetime, timezone

from speedrun_race_bot.models import Player, Race, RaceStatus


class RaceService:
    """In-memory race storage. Replace this with a database-backed repository later."""

    def __init__(self) -> None:
        self._races_by_channel: dict[int, Race] = {}
        self._races_by_interaction_id: dict[int, Race] = {}

    def get(self, channel_id: int) -> Race | None:
        return self._races_by_channel.get(channel_id)

    def get_by_interaction_id(self, interaction_id: int) -> Race | None:
        return self._races_by_interaction_id.get(interaction_id)

    def create(self, race: Race) -> Race:
        existing_race = self.get(race.channel_id)
        if existing_race and existing_race.status is not RaceStatus.COMPLETE:
            raise ValueError("This channel already has an active race.")
        self._races_by_channel[race.channel_id] = race
        self._races_by_interaction_id[race.interaction_id] = race
        return race

    def close(self, race: Race) -> None:
        """Remove a race from its channel while retaining RaceID history."""
        if self.get(race.channel_id) is not race:
            raise ValueError("That race is no longer active in this channel.")
        race.closed = True
        self._races_by_channel.pop(race.channel_id)

    def join(self, race: Race, user_id: int, display_name: str) -> None:
        if race.status is not RaceStatus.LOBBY:
            raise ValueError("The race has already started.")
        race.entrants.setdefault(user_id, Player(user_id, display_name))

    def leave(self, race: Race, user_id: int) -> None:
        if race.status is not RaceStatus.LOBBY:
            raise ValueError("The race has already started.")
        if user_id not in race.entrants:
            raise ValueError("Join the race before leaving it.")
        del race.entrants[user_id]

    def set_ready(self, race: Race, user_id: int) -> bool:
        if race.status is not RaceStatus.LOBBY:
            raise ValueError("The race has already started.")
        entrant = race.entrants.get(user_id)
        if not entrant:
            raise ValueError("Join the race before marking yourself ready.")
        return entrant.toggle_ready()

    def validate_start(self, race: Race | None, user_id: int) -> str | None:
        """Return why a race cannot start, or None when every check passes."""
        if not race:
            return "There is no active race in this channel."
        if user_id not in race.entrants:
            return "Only race participants can start this race."
        if race.status is not RaceStatus.LOBBY:
            return "This race cannot be started now."
        if race.countdown_in_progress:
            return "The race countdown is already running."
        if not race.entrants or not all(entrant.is_ready for entrant in race.entrants.values()):
            return "Every racer must click **Ready** before the race can start."
        if race.seed_generation_in_progress:
            return "The race seed is still being generated."
        if race.seed_generation_error:
            return "The race seed could not be generated, so this race cannot start."
        return None

    def start(self, race: Race, user_id: int) -> None:
        error = self.validate_start(race, user_id)
        if error:
            raise ValueError(error)
        race.status = RaceStatus.RUNNING
        race.started_at = datetime.now(timezone.utc)

    def finish(self, race: Race, user_id: int, display_name: str) -> None:
        if race.status is not RaceStatus.RUNNING:
            raise ValueError("The race has not started yet.")
        if not race.started_at:
            raise ValueError("The race timer is unavailable.")
        entrant = race.entrants.setdefault(user_id, Player(user_id, display_name))
        finish_position = 1 + sum(
            other.finish_position is not None for other in race.entrants.values()
        )
        entrant.record_finish(self._format_elapsed_time(race.started_at), finish_position)
        self._complete_if_all_results_recorded(race)

    def forfeit(self, race: Race, user_id: int) -> None:
        if race.status is not RaceStatus.RUNNING:
            raise ValueError("The race is not currently running.")
        entrant = race.entrants.get(user_id)
        if not entrant:
            raise ValueError("Join the race before forfeiting it.")
        entrant.record_forfeit()
        self._complete_if_all_results_recorded(race)

    @staticmethod
    def _complete_if_all_results_recorded(race: Race) -> None:
        if race.entrants and all(entrant.has_result for entrant in race.entrants.values()):
            race.status = RaceStatus.COMPLETE

    @staticmethod
    def _format_elapsed_time(started_at: datetime) -> str:
        elapsed_milliseconds = max(
            0, int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        )
        hours, remainder = divmod(elapsed_milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, milliseconds = divmod(remainder, 1_000)
        return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"
