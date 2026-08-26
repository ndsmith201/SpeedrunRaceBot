"""SQLite storage for data associated with Discord users."""

import csv
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


class UserRepository:
    DEFAULT_ELO = 1200

    def __init__(
        self,
        database_path: Path,
        schema_path: Path,
    ) -> None:
        self.database_path = database_path
        self.schema_path = schema_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get_flag(self, user_id: int) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT flag FROM user_data WHERE user_id = ?", (str(user_id),)
            ).fetchone()
        return row[0] if row else None

    def set_flag(self, user_id: int, flag: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_data (user_id, flag)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET flag = excluded.flag
                """,
                (str(user_id), flag),
            )

    def get_stream_url(self, user_id: int) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT stream_url FROM user_data WHERE user_id = ?", (str(user_id),)
            ).fetchone()
        return row[0] if row else None

    def set_stream_url(self, user_id: int, stream_url: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_data (user_id, stream_url)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET stream_url = excluded.stream_url
                """,
                (str(user_id), stream_url),
            )

    def ensure_user(self, user_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO user_data (user_id) VALUES (?)", (str(user_id),)
            )

    def get_elo(self, user_id: int) -> int:
        self.ensure_user(user_id)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT elo FROM user_data WHERE user_id = ?", (str(user_id),)
            ).fetchone()
        return int(row[0])

    def start_new_season(self, backup_directory: Path) -> Path:
        """Back up all user data to CSV, then reset every Elo rating."""
        backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_directory / f"user_data_{timestamp}.csv"
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute("SELECT * FROM user_data ORDER BY user_id")
            columns = [description[0] for description in cursor.description]
            rows = cursor.fetchall()
            with backup_path.open("x", encoding="utf-8", newline="") as backup_file:
                writer = csv.writer(backup_file)
                writer.writerow(columns)
                writer.writerows(rows)
            connection.execute("UPDATE user_data SET elo = ?", (self.DEFAULT_ELO,))
        return backup_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a transaction and always release the SQLite file handle."""
        connection = sqlite3.connect(self.database_path, timeout=10)
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
            legacy_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_flags'"
            ).fetchone()
            if legacy_table:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO user_data (user_id, flag)
                    SELECT user_id, flag FROM user_flags
                    """
                )
                connection.execute("DROP TABLE user_flags")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(user_data)")}
            if "stream_url" not in columns:
                connection.execute("ALTER TABLE user_data ADD COLUMN stream_url TEXT")
            if "elo" not in columns:
                connection.execute(
                    "ALTER TABLE user_data ADD COLUMN elo INTEGER NOT NULL DEFAULT 1200"
                )
