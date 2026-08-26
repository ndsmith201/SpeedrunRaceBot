"""Race state model."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

from speedrun_race_bot.models.player import Player


class RaceStatus(StrEnum):
    LOBBY = "Lobby"
    RUNNING = "Running"
    COMPLETE = "Complete"


@dataclass
class Race:
    guild_id: int
    channel_id: int
    voice_channel_id: int
    interaction_id: int
    host_id: int
    game: str
    category: str
    annotation: str | None = None
    status: RaceStatus = RaceStatus.LOBBY
    closed: bool = False
    countdown_in_progress: bool = False
    countdown_value: int | None = None
    countdown_starter_id: int | None = None
    show_go_emoji: bool = False
    started_at: datetime | None = None
    entrants: dict[int, Player] = field(default_factory=dict)
    status_message_id: int | None = None
    seed_filename: str | None = None
    seed_url: str | None = None
    seed_generation_in_progress: bool = False
    seed_generation_error: bool = False
    start_options: dict[str, str] = field(default_factory=dict)
    replay_urls: dict[int, str] = field(default_factory=dict)
    elo_processed: bool = False
    elo_api_synced: bool = False
    api_race_finished: bool = False
    elo_changes: dict[int, int] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
