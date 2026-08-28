import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from speedrun_race_bot.domain import Race, RaceStatus
from speedrun_race_bot.persistence import RaceRepository, UserRepository
from speedrun_race_bot.race.coordinator import RaceCoordinator
from speedrun_race_bot.race.state import RaceState

SCHEMA_PATH = Path("database/schema.sql")


def make_repositories(database_path: Path) -> tuple[RaceRepository, UserRepository]:
    return (
        RaceRepository(database_path, SCHEMA_PATH),
        UserRepository(database_path, SCHEMA_PATH),
    )


def make_race(
    interaction_id: int = 4,
    channel_id: int = 2,
    *,
    async_closes_at: datetime | None = None,
) -> Race:
    return Race(
        guild_id=1,
        channel_id=channel_id,
        voice_channel_id=3,
        interaction_id=interaction_id,
        host_id=10,
        game="SotN",
        category="safe",
        async_closes_at=async_closes_at,
    )


def test_races_table_contains_only_compact_history_fields(tmp_path: Path) -> None:
    repository, _ = make_repositories(tmp_path / "bot.sqlite3")

    with repository.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(races)").fetchall()}
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert columns == {
        "interaction_id",
        "channel_id",
        "message_id",
        "start_time",
        "end_time",
        "result",
    }
    assert "race_players" in tables
    assert "active_races" in tables
    assert "racers" not in tables


def test_players_have_a_many_to_many_relationship_with_races(tmp_path: Path) -> None:
    repository, users = make_repositories(tmp_path / "bot.sqlite3")
    races = RaceState(repository)
    for user_id in (10, 20):
        users.ensure_user(user_id)

    first = races.create(make_race())
    second = races.create(make_race(interaction_id=40, channel_id=5))
    races.join(first, 10, "First")
    races.join(first, 20, "Second")
    races.join(second, 10, "First")

    with repository.connect() as connection:
        links = {
            (row["race_id"], int(row["user_id"]))
            for row in connection.execute("SELECT race_id, user_id FROM race_players").fetchall()
        }
        foreign_keys = connection.execute("PRAGMA foreign_key_list(race_players)").fetchall()
        connection.execute("DELETE FROM races WHERE interaction_id = ?", (first.interaction_id,))
        remaining_links = connection.execute("SELECT race_id, user_id FROM race_players").fetchall()
        remaining_snapshots = connection.execute("SELECT race_id FROM active_races").fetchall()
        remaining_users = connection.execute("SELECT user_id FROM user_data").fetchall()

    assert links == {(4, 10), (4, 20), (40, 10)}
    assert {(key["table"], key["from"], key["to"], key["on_delete"]) for key in foreign_keys} == {
        ("races", "race_id", "interaction_id", "CASCADE"),
        ("user_data", "user_id", "user_id", "CASCADE"),
    }
    assert [(row["race_id"], int(row["user_id"])) for row in remaining_links] == [(40, 10)]
    assert [row["race_id"] for row in remaining_snapshots] == [40]
    assert {int(row["user_id"]) for row in remaining_users} == {10, 20}


def test_lifecycle_stores_timestamps_and_json_result(tmp_path: Path) -> None:
    repository, users = make_repositories(tmp_path / "bot.sqlite3")
    races = RaceState(repository)
    for user_id in (10, 20):
        users.ensure_user(user_id)

    race = races.create(make_race())
    races.join(race, 10, "First")
    races.join(race, 20, "Second")
    races.set_ready(race, 10)
    races.set_ready(race, 20)
    races.start(race, 10)
    races.finish(race, 10, "First")
    races.forfeit(race, 20)
    race.elo_changes = {10: 25, 20: -25}
    races.save_result(race)

    with repository.connect() as connection:
        row = connection.execute(
            "SELECT * FROM races WHERE interaction_id = ?", (race.interaction_id,)
        ).fetchone()

    assert row is not None
    assert datetime.fromisoformat(row["start_time"]).tzinfo is UTC
    assert datetime.fromisoformat(row["end_time"]) >= datetime.fromisoformat(row["start_time"])
    assert json.loads(row["result"]) == [
        {"player_name": "First", "elo_change": 25},
        {"player_name": "Second", "elo_change": -25},
    ]


def test_active_race_snapshot_survives_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "bot.sqlite3"
    repository, users = make_repositories(database_path)
    for user_id in (10, 20):
        users.ensure_user(user_id)
    races = RaceState(repository)
    race = races.create(make_race())
    races.join(race, 10, "First")
    races.join(race, 20, "Second", "second-api-user")
    races.record_tracker_message(race, 99)
    race.start_options = {"Randomizer preset": "Tournament"}
    race.seed_filename = "seed.ppf"
    race.seed_url = "https://example.com/seed.ppf"
    races.set_ready(race, 10)
    races.set_ready(race, 20)
    races.start(race, 10)
    races.finish(race, 10, "First")
    race.entrants[10].mark_api_result_synced()
    race.replay_urls[10] = "https://example.com/first.sotnr"
    races.save(race)

    restarted_repository = RaceRepository(database_path, SCHEMA_PATH)
    restarted_races = RaceState(restarted_repository)
    restored = restarted_races.active_races()[0]

    assert restarted_repository.get_message_reference(race.interaction_id) == (race.channel_id, 99)
    assert restored == race
    assert restarted_races.get(race.channel_id) is restored
    assert restarted_races.get_by_interaction_id(race.interaction_id) is restored


def test_closing_race_deletes_snapshot_but_keeps_history(tmp_path: Path) -> None:
    database_path = tmp_path / "bot.sqlite3"
    repository, users = make_repositories(database_path)
    users.ensure_user(10)
    races = RaceState(repository)
    race = races.create(make_race())
    races.join(race, 10, "First")
    races.record_tracker_message(race, 99)

    races.close(race)

    restarted_repository = RaceRepository(database_path, SCHEMA_PATH)
    with restarted_repository.connect() as connection:
        history = connection.execute(
            "SELECT end_time FROM races WHERE interaction_id = ?", (race.interaction_id,)
        ).fetchone()
    assert restarted_repository.list_active() == []
    assert restarted_repository.get_message_reference(race.interaction_id) == (race.channel_id, 99)
    assert history is not None
    assert history["end_time"] is not None


def test_new_race_replaces_current_snapshot_for_channel(tmp_path: Path) -> None:
    repository, _ = make_repositories(tmp_path / "bot.sqlite3")
    races = RaceState(repository)
    first = races.create(make_race())
    first.status = RaceStatus.COMPLETE
    races.save(first)

    second = races.create(make_race(interaction_id=40))

    assert [race.interaction_id for race in repository.list_active()] == [second.interaction_id]


def test_restore_recovers_transient_and_async_workflows(tmp_path: Path) -> None:
    database_path = tmp_path / "bot.sqlite3"
    repository, users = make_repositories(database_path)
    users.ensure_user(10)
    races = RaceState(repository)
    race = races.create(make_race(async_closes_at=datetime.now(UTC) + timedelta(hours=1)))
    races.join(race, 10, "Host")
    races.record_tracker_message(race, 99)
    races.start_async(race)
    race.countdown_in_progress = True
    race.countdown_value = 2
    race.countdown_starter_id = race.host_id
    race.show_go_emoji = True
    race.seed_generation_in_progress = True
    races.save(race)

    restored_races = RaceState(RaceRepository(database_path, SCHEMA_PATH))
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
    reloaded = RaceRepository(database_path, SCHEMA_PATH).list_active()[0]

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
