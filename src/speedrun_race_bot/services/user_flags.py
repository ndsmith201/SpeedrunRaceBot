"""Local storage for users' selected country-flag emojis."""

import json
from pathlib import Path


class UserFlagService:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._flags = self._load()

    def get(self, user_id: int) -> str | None:
        return self._flags.get(str(user_id))

    def set(self, user_id: int, flag: str) -> None:
        self._flags[str(user_id)] = flag
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._flags, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _load(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(user_id): flag for user_id, flag in data.items() if isinstance(flag, str)}
