"""SQLite storage for data associated with Discord users."""

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class UserDataService:
    DEFAULT_ELO = 1200
    ELO_K_FACTOR = 50

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
        with self._connect() as connection:
            row = connection.execute(
                "SELECT flag FROM user_data WHERE user_id = ?", (str(user_id),)
            ).fetchone()
        return row[0] if row else None

    def set_flag(self, user_id: int, flag: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_data (user_id, flag)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET flag = excluded.flag
                """,
                (str(user_id), flag),
            )

    def get_stream_url(self, user_id: int) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT stream_url FROM user_data WHERE user_id = ?", (str(user_id),)
            ).fetchone()
        return row[0] if row else None

    def set_stream_url(self, user_id: int, stream_url: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_data (user_id, stream_url)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET stream_url = excluded.stream_url
                """,
                (str(user_id), stream_url),
            )

    def ensure_user(self, user_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO user_data (user_id) VALUES (?)", (str(user_id),)
            )

    def get_elo(self, user_id: int) -> int:
        self.ensure_user(user_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT elo FROM user_data WHERE user_id = ?", (str(user_id),)
            ).fetchone()
        return int(row[0])

    def apply_race_elo(self, placements: dict[int, int]) -> dict[int, int]:
        """Apply a zero-sum-style pairwise Elo update for one completed race."""
        if not placements:
            return {}
        user_ids = list(placements)
        with self._connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO user_data (user_id) VALUES (?)",
                [(str(user_id),) for user_id in user_ids],
            )
            ratings = {
                int(user_id): int(elo)
                for user_id, elo in connection.execute(
                    f"SELECT user_id, elo FROM user_data WHERE user_id IN "
                    f"({','.join('?' for _ in user_ids)})",
                    [str(user_id) for user_id in user_ids],
                )
            }
            changes = self._calculate_elo_changes(ratings, placements)
            connection.executemany(
                "UPDATE user_data SET elo = MAX(0, elo + ?) WHERE user_id = ?",
                [(changes[user_id], str(user_id)) for user_id in user_ids],
            )
        return changes

    def adjust_race_elo(
        self,
        previous_changes: dict[int, int],
        ordered_user_ids: list[int],
    ) -> dict[int, int]:
        """Revert one race's Elo changes and apply replacements using a new finish order."""
        if not ordered_user_ids:
            raise ValueError("Supply at least one racer.")
        if len(set(ordered_user_ids)) != len(ordered_user_ids):
            raise ValueError("Each racer may only appear once.")
        if set(previous_changes) != set(ordered_user_ids):
            raise ValueError("The adjusted order must contain every original racer exactly once.")
        placements = {
            user_id: position for position, user_id in enumerate(ordered_user_ids, start=1)
        }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "UPDATE user_data SET elo = MAX(0, elo - ?) WHERE user_id = ?",
                [(previous_changes[user_id], str(user_id)) for user_id in ordered_user_ids],
            )
            ratings = {
                int(user_id): int(elo)
                for user_id, elo in connection.execute(
                    f"SELECT user_id, elo FROM user_data WHERE user_id IN "
                    f"({','.join('?' for _ in ordered_user_ids)})",
                    [str(user_id) for user_id in ordered_user_ids],
                )
            }
            if len(ratings) != len(ordered_user_ids):
                raise RuntimeError("Every adjusted racer must have an Elo record.")
            changes = self._calculate_elo_changes(ratings, placements)
            connection.executemany(
                "UPDATE user_data SET elo = MAX(0, elo + ?) WHERE user_id = ?",
                [(changes[user_id], str(user_id)) for user_id in ordered_user_ids],
            )
        return changes

    def _calculate_elo_changes(
        self, ratings: dict[int, int], placements: dict[int, int]
    ) -> dict[int, int]:
        user_ids = list(placements)
        raw_changes = {user_id: 0.0 for user_id in user_ids}
        divisor = max(1, len(user_ids) - 1)
        for index, user_id in enumerate(user_ids):
            for opponent_id in user_ids[index + 1 :]:
                expected = 1 / (1 + 10 ** ((ratings[opponent_id] - ratings[user_id]) / 400))
                if placements[user_id] < placements[opponent_id]:
                    score = 1.0
                elif placements[user_id] > placements[opponent_id]:
                    score = 0.0
                else:
                    score = 0.5
                change = self.ELO_K_FACTOR * (score - expected) / divisor
                raw_changes[user_id] += change
                raw_changes[opponent_id] -= change
        return {user_id: round(change) for user_id, change in raw_changes.items()}

    def start_new_season(self, backup_directory: Path) -> Path:
        """Back up all user data to CSV, then reset every Elo rating."""
        backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_directory / f"user_data_{timestamp}.csv"
        with self._connect() as connection:
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

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=10)

    def _initialize(self) -> None:
        schema = self.schema_path.read_text(encoding="utf-8")
        with self._connect() as connection:
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
