import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from speedrun_race_bot.domain import Race, RaceStatus
from speedrun_race_bot.persistence import RaceRepository
from speedrun_race_bot.race.coordinator import RaceCoordinator
from speedrun_race_bot.race.state import RaceState

SCHEMA_PATH = Path("database/schema.sql")


def make_races(database_path: Path) -> RaceState:
    return RaceState(RaceRepository(database_path, SCHEMA_PATH))


def make_race(interaction_id: int = 4) -> Race:
    return Race(
        guild_id=1,
        channel_id=2,
        voice_channel_id=3,
        interaction_id=interaction_id,
        host_id=5,
        game="SotN",
        category="safe",
        annotation="Database test",
        async_closes_at=datetime.now(UTC) + timedelta(hours=1),
    )


def test_race_and_racers_round_trip_after_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "bot.sqlite3"
    races = make_races(database_path)
    race = races.create(make_race())
    race.start_options = {"Randomizer preset": "Tournament", "Glitches": "No"}
    race.status_message_id = 99
    race.seed_filename = "seed.ppf"
    race.seed_url = "https://example.com/seed.ppf"
    races.join(race, 10, "First", "first-api-user")
    races.join(race, 20, "Second", "second-api-user")
    races.start_async(race, started_at=datetime.now(UTC) - timedelta(minutes=5))
    races.finish(race, 10, "First")
    races.forfeit(race, 20)
    race.entrants[10].mark_api_result_synced()
    race.entrants[20].mark_api_result_synced()
    race.replay_urls[10] = "https://example.com/first.sotnr"
    race.elo_changes = {10: 25, 20: -25}
    race.elo_processed = True
    race.elo_api_synced = True
    race.api_race_finished = True
    races.save(race)

    restored = make_races(database_path).get(race.channel_id)

    assert restored == race
    assert list(restored.entrants) == [10, 20]
    assert restored.replay_urls == {10: "https://example.com/first.sotnr"}
    assert restored.elo_changes == {10: 25, 20: -25}


def test_racers_have_a_cascading_many_to_one_foreign_key(tmp_path: Path) -> None:
    repository = RaceRepository(tmp_path / "bot.sqlite3", SCHEMA_PATH)
    races = RaceState(repository)
    race = races.create(make_race())
    races.join(race, 10, "First")
    races.join(race, 20, "Second")

    with repository.connect() as connection:
        foreign_keys = connection.execute("PRAGMA foreign_key_list(racers)").fetchall()
        racer_count = connection.execute(
            "SELECT COUNT(*) FROM racers WHERE race_id = ?", (race.interaction_id,)
        ).fetchone()[0]
        connection.execute("DELETE FROM races WHERE interaction_id = ?", (race.interaction_id,))
        remaining_racers = connection.execute(
            "SELECT COUNT(*) FROM racers WHERE race_id = ?", (race.interaction_id,)
        ).fetchone()[0]

    assert any(
        key[2] == "races" and key[3] == "race_id" and key[4] == "interaction_id"
        for key in foreign_keys
    )
    assert racer_count == 2
    assert remaining_racers == 0


def test_active_channel_lookup_and_race_history_survive_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "bot.sqlite3"
    races = make_races(database_path)
    first = races.create(make_race())
    first.status = RaceStatus.COMPLETE
    races.save(first)
    second = races.create(make_race(interaction_id=40))

    restored = make_races(database_path)

    assert restored.get(first.channel_id).interaction_id == second.interaction_id
    assert (
        restored.get_by_interaction_id(first.interaction_id).interaction_id == first.interaction_id
    )

    restored_second = restored.get(second.channel_id)
    restored.close(restored_second)
    after_close = make_races(database_path)

    assert after_close.get(second.channel_id) is None
    assert after_close.get_by_interaction_id(second.interaction_id).closed


def test_restore_recovers_transient_and_async_workflows(tmp_path: Path) -> None:
    database_path = tmp_path / "bot.sqlite3"
    races = make_races(database_path)
    race = races.create(make_race())
    races.join(race, race.host_id, "Host")
    races.start_async(race)
    race.countdown_in_progress = True
    race.countdown_value = 2
    race.countdown_starter_id = race.host_id
    race.show_go_emoji = True
    race.seed_generation_in_progress = True
    races.save(race)

    restored_races = make_races(database_path)
    scheduled_seeds = []
    scheduled_deadlines = []
    refreshed_races = []
    coordinator = object.__new__(RaceCoordinator)
    coordinator.service = restored_races
    coordinator.seed_delivery = SimpleNamespace(
        schedule=lambda restored_race, interaction_id: scheduled_seeds.append(
            (restored_race.interaction_id, interaction_id)
        )
    )
    coordinator._schedule_async_close = scheduled_deadlines.append
    coordinator.bot = SimpleNamespace(wait_until_ready=_wait_until_ready)
    coordinator.race_message = SimpleNamespace(update=_record_update(refreshed_races))
    coordinator.restore_tasks = set()

    async def restore() -> None:
        coordinator.restore_persisted_races()
        await asyncio.gather(*list(coordinator.restore_tasks))

    asyncio.run(restore())
    reloaded = make_races(database_path).get(race.channel_id)

    assert not reloaded.countdown_in_progress
    assert reloaded.countdown_value is None
    assert reloaded.countdown_starter_id is None
    assert not reloaded.show_go_emoji
    assert scheduled_seeds == [(race.interaction_id, race.interaction_id)]
    assert [restored.interaction_id for restored in scheduled_deadlines] == [race.interaction_id]
    assert refreshed_races == [race.interaction_id]


async def _wait_until_ready() -> None:
    return None


def _record_update(updated_races: list[int]):
    async def update(race: Race) -> None:
        updated_races.append(race.interaction_id)

    return update
