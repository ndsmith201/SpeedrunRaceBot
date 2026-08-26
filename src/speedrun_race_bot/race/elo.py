"""Transactional Elo calculation and correction for completed races."""

from speedrun_race_bot.persistence import UserRepository


class EloService:
    K_FACTOR = 50

    def __init__(self, users: UserRepository) -> None:
        self.users = users

    def apply(self, placements: dict[int, int]) -> dict[int, int]:
        """Apply a zero-sum-style pairwise Elo update for one completed race."""
        if not placements:
            return {}
        user_ids = list(placements)
        with self.users.connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO user_data (user_id) VALUES (?)",
                [(str(user_id),) for user_id in user_ids],
            )
            ratings = self._load_ratings(connection, user_ids)
            changes = self._calculate_changes(ratings, placements)
            connection.executemany(
                "UPDATE user_data SET elo = MAX(0, elo + ?) WHERE user_id = ?",
                [(changes[user_id], str(user_id)) for user_id in user_ids],
            )
        return changes

    def adjust(
        self, previous_changes: dict[int, int], ordered_user_ids: list[int]
    ) -> dict[int, int]:
        """Revert one race's Elo changes and apply a replacement finish order."""
        self._validate_order(previous_changes, ordered_user_ids)
        placements = {
            user_id: position for position, user_id in enumerate(ordered_user_ids, start=1)
        }
        with self.users.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "UPDATE user_data SET elo = MAX(0, elo - ?) WHERE user_id = ?",
                [(previous_changes[user_id], str(user_id)) for user_id in ordered_user_ids],
            )
            ratings = self._load_ratings(connection, ordered_user_ids)
            if len(ratings) != len(ordered_user_ids):
                raise RuntimeError("Every adjusted racer must have an Elo record.")
            changes = self._calculate_changes(ratings, placements)
            connection.executemany(
                "UPDATE user_data SET elo = MAX(0, elo + ?) WHERE user_id = ?",
                [(changes[user_id], str(user_id)) for user_id in ordered_user_ids],
            )
        return changes

    @staticmethod
    def _load_ratings(connection, user_ids: list[int]) -> dict[int, int]:
        return {
            int(user_id): int(elo)
            for user_id, elo in connection.execute(
                f"SELECT user_id, elo FROM user_data WHERE user_id IN "
                f"({','.join('?' for _ in user_ids)})",
                [str(user_id) for user_id in user_ids],
            )
        }

    def _calculate_changes(
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
                change = self.K_FACTOR * (score - expected) / divisor
                raw_changes[user_id] += change
                raw_changes[opponent_id] -= change
        return {user_id: round(change) for user_id, change in raw_changes.items()}

    @staticmethod
    def _validate_order(previous_changes: dict[int, int], ordered_user_ids: list[int]) -> None:
        if not ordered_user_ids:
            raise ValueError("Supply at least one racer.")
        if len(set(ordered_user_ids)) != len(ordered_user_ids):
            raise ValueError("Each racer may only appear once.")
        if set(previous_changes) != set(ordered_user_ids):
            raise ValueError("The adjusted order must contain every original racer exactly once.")
