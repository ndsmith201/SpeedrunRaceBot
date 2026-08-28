"""SQLite storage for compact race history and recoverable live snapshots."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from speedrun_race_bot.domain import Player, Race, RaceStatus

SNAPSHOT_VERSION = 1


class RaceRepository:
    def __init__(self, database_path: Path, schema_path: Path) -> None:
        self.database_path = database_path
        self.schema_path = schema_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create(self, race: Race) -> None:
        """Create permanent history and the one live snapshot for this channel."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                DELETE FROM active_races
                WHERE race_id IN (
                    SELECT interaction_id FROM races WHERE channel_id = ?
                )
                """,
                (race.channel_id,),
            )
            connection.execute(
                """
                INSERT INTO races (interaction_id, channel_id, message_id)
                VALUES (?, ?, ?)
                """,
                (race.interaction_id, race.channel_id, race.status_message_id),
            )
            connection.execute(
                "INSERT INTO active_races (race_id, snapshot) VALUES (?, ?)",
                (race.interaction_id, self._snapshot(race)),
            )

    def set_message_id(self, race: Race) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE races SET message_id = ? WHERE interaction_id = ?",
                (race.status_message_id, race.interaction_id),
            )
            self._save_active(connection, race)

    def get_message_reference(self, interaction_id: int) -> tuple[int, int] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT channel_id, message_id FROM races WHERE interaction_id = ?",
                (interaction_id,),
            ).fetchone()
        if not row or row["message_id"] is None:
            return None
        return int(row["channel_id"]), int(row["message_id"])

    def add_player(self, race: Race, user_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO race_players (race_id, user_id) VALUES (?, ?)",
                (race.interaction_id, str(user_id)),
            )
            self._save_active(connection, race)

    def remove_player(self, race: Race, user_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM race_players WHERE race_id = ? AND user_id = ?",
                (race.interaction_id, str(user_id)),
            )
            self._save_active(connection, race)

    def set_start_time(self, race: Race) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE races SET start_time = ? WHERE interaction_id = ?",
                (self._timestamp(race.started_at), race.interaction_id),
            )
            self._save_active(connection, race)

    def set_end_time(self, race: Race, end_time: datetime) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE races
                SET end_time = COALESCE(end_time, ?)
                WHERE interaction_id = ?
                """,
                (end_time.isoformat(), race.interaction_id),
            )
            self._save_active(connection, race)

    def set_result(
        self,
        race: Race,
        result: list[dict[str, str | int]],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE races SET result = ? WHERE interaction_id = ?",
                (json.dumps(result), race.interaction_id),
            )
            self._save_active(connection, race)

    def save_active(self, race: Race) -> None:
        with self.connect() as connection:
            self._save_active(connection, race)

    def close(self, race: Race, end_time: datetime) -> None:
        """Finish permanent history and discard the no-longer-needed live snapshot."""
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE races
                SET end_time = COALESCE(end_time, ?)
                WHERE interaction_id = ?
                """,
                (end_time.isoformat(), race.interaction_id),
            )
            connection.execute(
                "DELETE FROM active_races WHERE race_id = ?",
                (race.interaction_id,),
            )

    def list_active(self) -> list[Race]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT snapshot FROM active_races ORDER BY race_id"
            ).fetchall()
        return [self._race_from_snapshot(str(row["snapshot"])) for row in rows]

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

    def _save_active(self, connection: sqlite3.Connection, race: Race) -> None:
        connection.execute(
            "UPDATE active_races SET snapshot = ? WHERE race_id = ?",
            (self._snapshot(race), race.interaction_id),
        )

    @classmethod
    def _snapshot(cls, race: Race) -> str:
        return json.dumps(
            {"version": SNAPSHOT_VERSION, "race": asdict(race)},
            default=cls._json_default,
            sort_keys=True,
        )

    @classmethod
    def _race_from_snapshot(cls, snapshot: str) -> Race:
        payload = json.loads(snapshot)
        if payload.get("version") != SNAPSHOT_VERSION:
            raise ValueError("Unsupported active race snapshot version.")
        data = payload["race"]
        data["status"] = RaceStatus(data["status"])
        for name in ("started_at", "async_closes_at", "created_at"):
            data[name] = cls._datetime(data[name])
        data["entrants"] = {
            int(user_id): Player(**player) for user_id, player in data["entrants"].items()
        }
        data["replay_urls"] = {int(user_id): url for user_id, url in data["replay_urls"].items()}
        data["elo_changes"] = {
            int(user_id): change for user_id, change in data["elo_changes"].items()
        }
        return Race(**data)

    @staticmethod
    def _json_default(value: object) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f"Cannot store {type(value).__name__} in a race snapshot.")

    @staticmethod
    def _timestamp(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    @staticmethod
    def _datetime(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None
