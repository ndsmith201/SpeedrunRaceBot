import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from speedrun_race_bot.domain import Race, RaceStatus
from speedrun_race_bot.race.coordinator import RaceCoordinator
from speedrun_race_bot.race.results import RaceResults
from speedrun_race_bot.race.state import RaceState


class NoApiCallsAllowed:
    def __getattr__(self, method_name: str):
        async def fail(*args: object, **kwargs: object) -> None:
            raise AssertionError(f"Async race called API method {method_name}")

        return fail


class FakeTracker:
    def __init__(self) -> None:
        self.updates = 0

    async def update(self, race: Race) -> None:
        self.updates += 1


class FakeElo:
    def apply(self, placements: dict[int, int]) -> dict[int, int]:
        return {user_id: 0 for user_id in placements}


def make_async_race() -> Race:
    return Race(
        guild_id=1,
        channel_id=2,
        voice_channel_id=None,
        interaction_id=3,
        host_id=10,
        game="SotN",
        category="",
        async_closes_at=datetime.now(UTC) + timedelta(hours=1),
    )


def test_async_join_does_not_call_the_api() -> None:
    races = RaceState()
    race = races.create(make_async_race())
    races.join(race, 10, "Host")
    races.start_async(race)
    tracker = FakeTracker()
    coordinator = object.__new__(RaceCoordinator)
    coordinator.service = races
    coordinator.user_data = SimpleNamespace(ensure_user=lambda user_id: None)
    coordinator.rando_api = NoApiCallsAllowed()
    coordinator.race_message = tracker
    coordinator.voice_announcer = SimpleNamespace()
    interaction = SimpleNamespace(
        channel_id=race.channel_id,
        guild=None,
        user=SimpleNamespace(id=20, name="discord-user", display_name="Late racer"),
    )

    result = asyncio.run(coordinator.join_race(interaction))

    assert result == "You joined the race!"
    assert race.entrants[20].api_name is None
    assert tracker.updates == 1


def test_async_join_targets_async_race_when_live_race_shares_channel() -> None:
    races = RaceState()
    live_race = Race(
        guild_id=1,
        channel_id=2,
        voice_channel_id=4,
        interaction_id=5,
        host_id=10,
        game="SotN",
        category="",
    )
    races.create(live_race)
    async_race = races.create(make_async_race())
    races.join(async_race, 10, "Host")
    races.start_async(async_race)
    coordinator = object.__new__(RaceCoordinator)
    coordinator.service = races
    coordinator.user_data = SimpleNamespace(ensure_user=lambda user_id: None)
    coordinator.rando_api = NoApiCallsAllowed()
    coordinator.race_message = FakeTracker()
    coordinator.voice_announcer = SimpleNamespace()
    interaction = SimpleNamespace(
        channel_id=async_race.channel_id,
        guild=None,
        user=SimpleNamespace(id=20, name="discord-user", display_name="Late racer"),
    )

    result = asyncio.run(coordinator.join_race(interaction, is_async=True))

    assert result == "You joined the race!"
    assert 20 in async_race.entrants
    assert 20 not in live_race.entrants


def test_async_results_and_finalization_do_not_call_the_api() -> None:
    races = RaceState()
    race = races.create(make_async_race())
    races.join(race, 10, "Finisher")
    races.join(race, 20, "No result")
    races.start_async(race, started_at=datetime.now(UTC) - timedelta(minutes=5))
    tracker = FakeTracker()
    results = RaceResults(
        races,
        SimpleNamespace(),
        FakeElo(),
        NoApiCallsAllowed(),
        tracker,
    )
    interaction = SimpleNamespace(
        channel_id=race.channel_id,
        user=SimpleNamespace(id=10, name="discord-user", display_name="Finisher"),
    )

    finish_error = asyncio.run(results.record_finish(interaction))
    finalize_error = asyncio.run(results.finalize_async_race(race))

    assert finish_error is None
    assert finalize_error is None
    assert race.status is RaceStatus.COMPLETE
    assert race.entrants[10].api_result_synced
    assert race.entrants[20].forfeited
    assert race.entrants[20].api_result_synced
    assert race.elo_processed
    assert race.elo_api_synced
    assert race.api_race_finished
