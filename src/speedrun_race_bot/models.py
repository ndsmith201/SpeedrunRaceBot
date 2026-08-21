from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class RaceStatus(StrEnum):
    LOBBY = "Lobby"
    RUNNING = "Running"
    COMPLETE = "Complete"


@dataclass
class Entrant:
    user_id: int
    display_name: str
    is_ready: bool = False
    finish_time: str | None = None
    finish_position: int | None = None
    forfeited: bool = False


@dataclass
class Race:
    guild_id: int
    channel_id: int
    voice_channel_id: int
    host_id: int
    game: str
    category: str
    annotation: str | None = None
    status: RaceStatus = RaceStatus.LOBBY
    countdown_in_progress: bool = False
    countdown_value: int | None = None
    countdown_starter_id: int | None = None
    show_go_emoji: bool = False
    started_at: datetime | None = None
    entrants: dict[int, Entrant] = field(default_factory=dict)
    status_message_id: int | None = None
    seed_filename: str | None = None
    seed_url: str | None = None
    seed_generation_in_progress: bool = False
    seed_generation_error: bool = False
    start_options: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
