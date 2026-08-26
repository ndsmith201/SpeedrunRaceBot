from speedrun_race_bot.domain import Race, RaceStatus
from speedrun_race_bot.race.state import RaceState


def make_race() -> Race:
    return Race(
        guild_id=1,
        channel_id=2,
        voice_channel_id=3,
        interaction_id=4,
        host_id=5,
        game="SotN",
        category="safe",
    )


def test_closing_removes_channel_lookup_but_preserves_race_id_history() -> None:
    races = RaceState()
    race = races.create(make_race())

    races.close(race)

    assert race.closed
    assert races.get(race.channel_id) is None
    assert races.get_by_interaction_id(race.interaction_id) is race


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
