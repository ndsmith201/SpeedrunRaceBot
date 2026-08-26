"""Environment configuration for the standalone seed generator."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class SeedGeneratorConfig:
    interaction_id: int
    start_options: dict[str, str]
    seedbank_generation: bool
    rando_path: Path
    patch_folder: Path
    seeds_directory: Path
    replays_folder: Path
    node_executable: str = "node"

    @property
    def randomizer_script(self) -> Path:
        return self.rando_path / "randomize"

    def option_enabled(self, name: str, *, default: bool = False) -> bool:
        value = self.start_options.get(name)
        if value is None:
            return default
        normalized_value = value.strip().casefold()
        if normalized_value not in {"true", "false"}:
            raise RuntimeError(f"Race option {name!r} must be either 'true' or 'false'.")
        return normalized_value == "true"


def load_config() -> SeedGeneratorConfig:
    """Load randomizer configuration from the project's `.env` and race environment."""
    project_directory = Path(__file__).resolve().parents[2]
    load_dotenv(project_directory / ".env")
    return SeedGeneratorConfig(
        interaction_id=_required_integer("RACE_INTERACTION_ID"),
        start_options=_start_options(),
        seedbank_generation=os.getenv("RACE_SEEDBANK_GENERATION", "").casefold() == "true",
        rando_path=_required_path("RANDO_PATH", project_directory),
        patch_folder=_required_path("PATCH_FOLDER", project_directory),
        seeds_directory=_required_path("RACE_SEEDS_DIRECTORY", project_directory),
        replays_folder=_required_path("REPLAYS_FOLDER", project_directory),
        node_executable=os.getenv("NODE_EXECUTABLE", "node").strip() or "node",
    )


def _required_integer(variable: str) -> int:
    value = os.getenv(variable, "").strip()
    if not value:
        raise RuntimeError(f"{variable} was not provided by the race bot.")
    try:
        return int(value)
    except ValueError as error:
        raise RuntimeError(f"{variable} must be an integer.") from error


def _start_options() -> dict[str, str]:
    raw_options = os.getenv("RACE_START_OPTIONS", "").strip()
    if not raw_options:
        raise RuntimeError("RACE_START_OPTIONS was not provided by the race bot.")
    try:
        start_options = json.loads(raw_options)
    except json.JSONDecodeError as error:
        raise RuntimeError("RACE_START_OPTIONS must contain valid JSON.") from error
    if not isinstance(start_options, dict) or not all(
        isinstance(name, str) and isinstance(value, str) for name, value in start_options.items()
    ):
        raise RuntimeError("RACE_START_OPTIONS must contain a JSON object of string values.")
    return start_options


def _required_path(variable: str, project_directory: Path) -> Path:
    value = os.getenv(variable, "").strip()
    if not value:
        raise RuntimeError(f"Set {variable} in the .env file.")
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_directory / path
