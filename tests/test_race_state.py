from datetime import UTC, datetime, timedelta

from speedrun_race_bot.domain import Race, RaceStatus
from speedrun_race_bot.race.state import RaceState


def make_race(*, async_closes_at: datetime | None = None) -> Race:
    return Race(
        guild_id=1,
        channel_id=2,
        voice_channel_id=3,
        interaction_id=4,
        host_id=5,
        game="SotN",
        category="safe",
        async_closes_at=async_closes_at,
    )


def test_closing_removes_channel_lookup_but_preserves_race_id_history() -> None:
    races = RaceState()
    race = races.create(make_race())

    races.close(race)

    assert race.closed
    assert races.get(race.channel_id) is None
    assert races.get_by_interaction_id(race.interaction_id) is race


def test_live_and_async_races_can_be_active_in_the_same_channel() -> None:
    races = RaceState()
    live_race = races.create(make_race())
    async_race = make_race(async_closes_at=datetime.now(UTC) + timedelta(hours=1))
    async_race.interaction_id = 40

    races.create(async_race)

    assert races.get(live_race.channel_id, is_async=False) is live_race
    assert races.get(live_race.channel_id, is_async=True) is async_race
    assert races.in_channel(live_race.channel_id) == [live_race, async_race]

    races.close(async_race)

    assert races.get(live_race.channel_id, is_async=False) is live_race
    assert races.get(live_race.channel_id, is_async=True) is None


def test_channel_rejects_a_second_race_of_the_same_type() -> None:
    races = RaceState()
    races.create(make_race())
    duplicate = make_race()
    duplicate.interaction_id = 40

    try:
        races.create(duplicate)
    except ValueError as error:
        assert str(error) == "This channel already has an active race."
    else:
        raise AssertionError("Expected a duplicate live race to be rejected")


def test_all_results_complete_a_running_race() -> None:
    races = RaceState()
    race = races.create(make_race())
    races.join(race, 10, "First")
    races.join(race, 20, "Second")
    race.status = RaceStatus.RUNNING
    race.started_at = race.created_at

    races.finish(race, 10, "First")
    races.forfeit(race, 20)

    assert race.status is RaceStatus.COMPLETE
    assert race.entrants[10].finish_position == 1
    assert race.entrants[20].forfeited


def test_async_race_accepts_late_entrants_and_waits_for_deadline() -> None:
    races = RaceState()
    race = races.create(make_race(async_closes_at=datetime.now(UTC) + timedelta(hours=1)))
    races.join(race, 10, "First", "first-user")
    races.start_async(race, started_at=datetime.now(UTC) - timedelta(minutes=5))

    races.finish(race, 10, "First")
    races.join(race, 20, "Late entrant", "late-user")

    assert race.status is RaceStatus.RUNNING
    assert race.entrants[10].has_result
    assert not race.entrants[20].has_result

    races.complete_async(race)

    assert race.status is RaceStatus.COMPLETE
    assert race.entrants[20].forfeited


def test_async_race_rejects_submissions_after_deadline() -> None:
    races = RaceState()
    race = races.create(make_race(async_closes_at=datetime.now(UTC) - timedelta(seconds=1)))
    races.join(race, 10, "First", "first-user")
    races.start_async(race)

    try:
        races.finish(race, 10, "First")
    except ValueError as error:
        assert str(error) == "This async race is closed."
    else:
        raise AssertionError("Expected an expired async race to reject the finish")
