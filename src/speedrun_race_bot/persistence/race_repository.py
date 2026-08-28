"""SQLite storage for compact race history records."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


class RaceRepository:
    def __init__(self, database_path: Path, schema_path: Path) -> None:
        self.database_path = database_path
        self.schema_path = schema_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create(self, interaction_id: int, channel_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO races (interaction_id, channel_id) VALUES (?, ?)",
                (interaction_id, channel_id),
            )

    def set_message_id(self, interaction_id: int, message_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE races SET message_id = ? WHERE interaction_id = ?",
                (message_id, interaction_id),
            )

    def get_message_reference(self, interaction_id: int) -> tuple[int, int] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT channel_id, message_id FROM races WHERE interaction_id = ?",
                (interaction_id,),
            ).fetchone()
        if not row or row["message_id"] is None:
            return None
        return int(row["channel_id"]), int(row["message_id"])

    def add_player(self, interaction_id: int, user_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO race_players (race_id, user_id) VALUES (?, ?)",
                (interaction_id, str(user_id)),
            )

    def remove_player(self, interaction_id: int, user_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM race_players WHERE race_id = ? AND user_id = ?",
                (interaction_id, str(user_id)),
            )

    def set_start_time(self, interaction_id: int, start_time: datetime) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE races SET start_time = ? WHERE interaction_id = ?",
                (start_time.isoformat(), interaction_id),
            )

    def set_end_time(self, interaction_id: int, end_time: datetime) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE races
                SET end_time = COALESCE(end_time, ?)
                WHERE interaction_id = ?
                """,
                (end_time.isoformat(), interaction_id),
            )

    def set_result(
        self,
        interaction_id: int,
        result: list[dict[str, str | int]],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE races SET result = ? WHERE interaction_id = ?",
                (json.dumps(result), interaction_id),
            )

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
