from datetime import UTC, datetime

from speedrun_race_bot.domain import Player, Race, RaceStatus
from speedrun_race_bot.persistence import RaceRepository


class RaceState:
    """Own live race state and record compact race history in SQLite."""

    def __init__(self, repository: RaceRepository | None = None) -> None:
        self.repository = repository
        self._races_by_channel_and_type: dict[tuple[int, bool], Race] = {}
        self._races_by_interaction_id: dict[int, Race] = {}

    def get(self, channel_id: int, *, is_async: bool | None = None) -> Race | None:
        """Return a channel race, optionally selecting its live or async slot."""
        if is_async is not None:
            return self._races_by_channel_and_type.get((channel_id, is_async))
        races = self.in_channel(channel_id)
        if len(races) > 1:
            raise ValueError("This channel has both a live race and an async race.")
        return races[0] if races else None

    def in_channel(self, channel_id: int) -> list[Race]:
        return [
            race
            for is_async in (False, True)
            if (race := self._races_by_channel_and_type.get((channel_id, is_async)))
        ]

    def get_by_interaction_id(self, interaction_id: int) -> Race | None:
        return self._races_by_interaction_id.get(interaction_id)

    def active_races(self) -> list[Race]:
        if not self.repository:
            return list(self._races_by_channel_and_type.values())
        races = []
        for loaded_race in self.repository.list_active():
            race = self._races_by_interaction_id.get(loaded_race.interaction_id, loaded_race)
            self._remember(race)
            races.append(race)
        return races

    def create(self, race: Race) -> Race:
        existing_race = self.get(race.channel_id, is_async=race.is_async)
        if existing_race and existing_race.status is not RaceStatus.COMPLETE:
            raise ValueError("This channel already has an active race.")
        if self.repository:
            self.repository.create(race)
        self._remember(race)
        return race

    def record_tracker_message(self, race: Race, message_id: int) -> None:
        race.status_message_id = message_id
        if self.repository:
            self.repository.set_message_id(race)

    def close(self, race: Race) -> None:
        """Remove a race from its channel while retaining RaceID history."""
        if self.get(race.channel_id, is_async=race.is_async) is not race:
            raise ValueError("That race is no longer active in this channel.")
        race.closed = True
        self._races_by_channel_and_type.pop((race.channel_id, race.is_async))
        if self.repository:
            self.repository.close(race, datetime.now(UTC))

    def save(self, race: Race) -> None:
        if self.repository:
            self.repository.save_active(race)

    def join(
        self, race: Race, user_id: int, display_name: str, api_name: str | None = None
    ) -> None:
        async_race_is_open = (
            race.is_async
            and race.status is RaceStatus.RUNNING
            and race.async_closes_at is not None
            and datetime.now(UTC) < race.async_closes_at
        )
        if race.status is not RaceStatus.LOBBY and not async_race_is_open:
            raise ValueError("The race has already started.")
        entrant = race.entrants.setdefault(user_id, Player(user_id, display_name, api_name))
        if api_name and not entrant.api_name:
            entrant.api_name = api_name
        if self.repository:
            self.repository.add_player(race, user_id)

    def leave(self, race: Race, user_id: int) -> None:
        if race.status is not RaceStatus.LOBBY:
            raise ValueError("The race has already started.")
        if user_id not in race.entrants:
            raise ValueError("Join the race before leaving it.")
        del race.entrants[user_id]
        if self.repository:
            self.repository.remove_player(race, user_id)

    def set_ready(self, race: Race, user_id: int) -> bool:
        if race.status is not RaceStatus.LOBBY:
            raise ValueError("The race has already started.")
        entrant = race.entrants.get(user_id)
        if not entrant:
            raise ValueError("Join the race before marking yourself ready.")
        is_ready = entrant.toggle_ready()
        self.save(race)
        return is_ready

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
        race.started_at = datetime.now(UTC)
        if self.repository:
            self.repository.set_start_time(race)

    def start_async(self, race: Race, *, started_at: datetime | None = None) -> None:
        if not race.is_async:
            raise ValueError("That is not an async race.")
        if race.status is not RaceStatus.LOBBY:
            raise ValueError("This race cannot be started now.")
        race.status = RaceStatus.RUNNING
        race.started_at = started_at or datetime.now(UTC)
        if self.repository:
            self.repository.set_start_time(race)

    def finish(self, race: Race, user_id: int, display_name: str) -> None:
        if race.status is not RaceStatus.RUNNING:
            raise ValueError("The race has not started yet.")
        if not race.started_at:
            raise ValueError("The race timer is unavailable.")
        if race.is_async and race.async_closes_at and datetime.now(UTC) >= race.async_closes_at:
            raise ValueError("This async race is closed.")
        if race.is_async and user_id not in race.entrants:
            raise ValueError("Join the async race before submitting a finish.")
        entrant = race.entrants.setdefault(user_id, Player(user_id, display_name))
        finish_position = 1 + sum(
            other.finish_position is not None for other in race.entrants.values()
        )
        entrant.record_finish(self._format_elapsed_time(race.started_at), finish_position)
        if self._complete_if_all_results_recorded(race):
            self._record_end_time(race)
        else:
            self.save(race)

    def forfeit(self, race: Race, user_id: int) -> None:
        if race.status is not RaceStatus.RUNNING:
            raise ValueError("The race is not currently running.")
        entrant = race.entrants.get(user_id)
        if not entrant:
            raise ValueError("Join the race before forfeiting it.")
        entrant.record_forfeit()
        if self._complete_if_all_results_recorded(race):
            self._record_end_time(race)
        else:
            self.save(race)

    def complete_async(self, race: Race) -> None:
        """Close async entry submission and forfeit racers without a result."""
        if not race.is_async:
            raise ValueError("That is not an async race.")
        if race.status is RaceStatus.COMPLETE:
            return
        if race.status is not RaceStatus.RUNNING:
            raise ValueError("The async race is not currently running.")
        for entrant in race.entrants.values():
            if not entrant.has_result:
                entrant.record_forfeit()
        race.status = RaceStatus.COMPLETE
        self._record_end_time(race)

    def save_result(self, race: Race) -> None:
        if not self.repository:
            return
        result = [
            {
                "player_name": entrant.display_name,
                "elo_change": race.elo_changes.get(user_id, 0),
            }
            for user_id, entrant in race.entrants.items()
        ]
        self.repository.set_result(race, result)

    def _record_end_time(self, race: Race) -> None:
        if self.repository:
            self.repository.set_end_time(race, datetime.now(UTC))

    def _remember(self, race: Race) -> None:
        self._races_by_channel_and_type[(race.channel_id, race.is_async)] = race
        self._races_by_interaction_id[race.interaction_id] = race

    @staticmethod
    def _complete_if_all_results_recorded(race: Race) -> bool:
        if (
            not race.is_async
            and race.entrants
            and all(entrant.has_result for entrant in race.entrants.values())
        ):
            race.status = RaceStatus.COMPLETE
            return True
        return False

    @staticmethod
    def _format_elapsed_time(started_at: datetime) -> str:
        elapsed_milliseconds = max(0, int((datetime.now(UTC) - started_at).total_seconds() * 1000))
        hours, remainder = divmod(elapsed_milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, milliseconds = divmod(remainder, 1_000)
        return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"
