"""Player state and player-specific mutations."""

from dataclasses import dataclass


@dataclass
class Player:
    user_id: int
    display_name: str
    is_ready: bool = False
    finish_time: str | None = None
    finish_position: int | None = None
    forfeited: bool = False
    api_result_synced: bool = False

    @property
    def has_result(self) -> bool:
        return self.finish_position is not None or self.forfeited

    def toggle_ready(self) -> bool:
        self.is_ready = not self.is_ready
        return self.is_ready

    def record_finish(self, finish_time: str, finish_position: int) -> None:
        if self.forfeited:
            raise ValueError("You forfeited this race and cannot submit a finish time.")
        if self.finish_position is not None:
            raise ValueError("You already submitted a finish time.")
        self.finish_time = finish_time
        self.finish_position = finish_position

    def record_forfeit(self) -> None:
        if self.finish_position is not None:
            raise ValueError("You already finished this race.")
        if self.forfeited:
            raise ValueError("You already forfeited this race.")
        self.forfeited = True

    def mark_api_result_synced(self) -> None:
        self.api_result_synced = True
