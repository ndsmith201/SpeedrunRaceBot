"""SQLite repository for races and their one-to-many racer records."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from speedrun_race_bot.domain import Player, Race, RaceStatus


class RaceRepository:
    def __init__(self, database_path: Path, schema_path: Path) -> None:
        self.database_path = database_path
        self.schema_path = schema_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create(self, race: Race) -> None:
        """Insert a race and make it the active race for its channel."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE races SET active = 0 WHERE channel_id = ? AND active = 1",
                (race.channel_id,),
            )
            self._write(connection, race, active=True)

    def save(self, race: Race) -> None:
        """Persist the current race aggregate without changing its active status."""
        with self.connect() as connection:
            active_row = connection.execute(
                "SELECT active FROM races WHERE interaction_id = ?",
                (race.interaction_id,),
            ).fetchone()
            active = bool(active_row[0]) if active_row else not race.closed
            self._write(connection, race, active=active)

    def close(self, race: Race) -> None:
        """Persist a closed race and remove it from active channel lookup."""
        with self.connect() as connection:
            self._write(connection, race, active=False)

    def get_by_channel(self, channel_id: int) -> Race | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM races WHERE channel_id = ? AND active = 1",
                (channel_id,),
            ).fetchone()
            return self._load(connection, row) if row else None

    def get_by_interaction_id(self, interaction_id: int) -> Race | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM races WHERE interaction_id = ?",
                (interaction_id,),
            ).fetchone()
            return self._load(connection, row) if row else None

    def list_active(self) -> list[Race]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM races WHERE active = 1 ORDER BY created_at"
            ).fetchall()
            return [self._load(connection, row) for row in rows]

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        schema = self.schema_path.read_text(encoding="utf-8")
        with self.connect() as connection:
            connection.executescript(schema)

    def _write(self, connection: sqlite3.Connection, race: Race, *, active: bool) -> None:
        connection.execute(
            """
            INSERT INTO races (
                interaction_id, guild_id, channel_id, voice_channel_id, host_id, game,
                category, annotation, status, closed, active, countdown_in_progress,
                countdown_value, countdown_starter_id, show_go_emoji, started_at,
                status_message_id, seed_filename, seed_url, seed_generation_in_progress,
                seed_generation_error, start_options, elo_processed, elo_api_synced,
                api_race_finished, async_closes_at, created_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(interaction_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                channel_id = excluded.channel_id,
                voice_channel_id = excluded.voice_channel_id,
                host_id = excluded.host_id,
                game = excluded.game,
                category = excluded.category,
                annotation = excluded.annotation,
                status = excluded.status,
                closed = excluded.closed,
                active = excluded.active,
                countdown_in_progress = excluded.countdown_in_progress,
                countdown_value = excluded.countdown_value,
                countdown_starter_id = excluded.countdown_starter_id,
                show_go_emoji = excluded.show_go_emoji,
                started_at = excluded.started_at,
                status_message_id = excluded.status_message_id,
                seed_filename = excluded.seed_filename,
                seed_url = excluded.seed_url,
                seed_generation_in_progress = excluded.seed_generation_in_progress,
                seed_generation_error = excluded.seed_generation_error,
                start_options = excluded.start_options,
                elo_processed = excluded.elo_processed,
                elo_api_synced = excluded.elo_api_synced,
                api_race_finished = excluded.api_race_finished,
                async_closes_at = excluded.async_closes_at,
                created_at = excluded.created_at
            """,
            (
                race.interaction_id,
                race.guild_id,
                race.channel_id,
                race.voice_channel_id,
                race.host_id,
                race.game,
                race.category,
                race.annotation,
                race.status.value,
                race.closed,
                active,
                race.countdown_in_progress,
                race.countdown_value,
                race.countdown_starter_id,
                race.show_go_emoji,
                self._timestamp(race.started_at),
                race.status_message_id,
                race.seed_filename,
                race.seed_url,
                race.seed_generation_in_progress,
                race.seed_generation_error,
                json.dumps(race.start_options, sort_keys=True),
                race.elo_processed,
                race.elo_api_synced,
                race.api_race_finished,
                self._timestamp(race.async_closes_at),
                self._timestamp(race.created_at),
            ),
        )
        connection.execute("DELETE FROM racers WHERE race_id = ?", (race.interaction_id,))
        connection.executemany(
            """
            INSERT INTO racers (
                race_id, user_id, joined_order, display_name, api_name, is_ready,
                finish_time, finish_position, forfeited, api_result_synced,
                replay_url, elo_change
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    race.interaction_id,
                    entrant.user_id,
                    joined_order,
                    entrant.display_name,
                    entrant.api_name,
                    entrant.is_ready,
                    entrant.finish_time,
                    entrant.finish_position,
                    entrant.forfeited,
                    entrant.api_result_synced,
                    race.replay_urls.get(entrant.user_id),
                    race.elo_changes.get(entrant.user_id),
                )
                for joined_order, entrant in enumerate(race.entrants.values())
            ],
        )

    def _load(self, connection: sqlite3.Connection, row: sqlite3.Row) -> Race:
        race = Race(
            guild_id=int(row["guild_id"]),
            channel_id=int(row["channel_id"]),
            voice_channel_id=self._optional_int(row["voice_channel_id"]),
            interaction_id=int(row["interaction_id"]),
            host_id=int(row["host_id"]),
            game=str(row["game"]),
            category=str(row["category"]),
            annotation=row["annotation"],
            status=RaceStatus(row["status"]),
            closed=bool(row["closed"]),
            countdown_in_progress=bool(row["countdown_in_progress"]),
            countdown_value=self._optional_int(row["countdown_value"]),
            countdown_starter_id=self._optional_int(row["countdown_starter_id"]),
            show_go_emoji=bool(row["show_go_emoji"]),
            started_at=self._datetime(row["started_at"]),
            status_message_id=self._optional_int(row["status_message_id"]),
            seed_filename=row["seed_filename"],
            seed_url=row["seed_url"],
            seed_generation_in_progress=bool(row["seed_generation_in_progress"]),
            seed_generation_error=bool(row["seed_generation_error"]),
            start_options=json.loads(row["start_options"]),
            elo_processed=bool(row["elo_processed"]),
            elo_api_synced=bool(row["elo_api_synced"]),
            api_race_finished=bool(row["api_race_finished"]),
            async_closes_at=self._datetime(row["async_closes_at"]),
            created_at=self._datetime(row["created_at"]),
        )
        racer_rows = connection.execute(
            "SELECT * FROM racers WHERE race_id = ? ORDER BY joined_order",
            (race.interaction_id,),
        ).fetchall()
        for racer in racer_rows:
            user_id = int(racer["user_id"])
            race.entrants[user_id] = Player(
                user_id=user_id,
                display_name=str(racer["display_name"]),
                api_name=racer["api_name"],
                is_ready=bool(racer["is_ready"]),
                finish_time=racer["finish_time"],
                finish_position=self._optional_int(racer["finish_position"]),
                forfeited=bool(racer["forfeited"]),
                api_result_synced=bool(racer["api_result_synced"]),
            )
            if racer["replay_url"] is not None:
                race.replay_urls[user_id] = str(racer["replay_url"])
            if racer["elo_change"] is not None:
                race.elo_changes[user_id] = int(racer["elo_change"])
        return race

    @staticmethod
    def _timestamp(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    @staticmethod
    def _datetime(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    @staticmethod
    def _optional_int(value: int | None) -> int | None:
        return int(value) if value is not None else None
