"""Optional randomizer seed-generation command support."""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import TextIO

from speedrun_race_bot.domain import Race

logger = logging.getLogger(__name__)
SEEDBANK_PRESET = "beyond-confirmed-sum26te"
_seedbank_generation_lock = asyncio.Lock()


def file_signature(path: Path) -> tuple[int, int]:
    """Return values that identify a file version without reading its contents."""
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


async def capture_and_echo(stream: asyncio.StreamReader, destination: TextIO) -> str:
    """Echo a seed command stream live while retaining its text for error reporting."""
    chunks = []
    while chunk := await stream.readline():
        text = chunk.decode(errors="replace")
        chunks.append(text)
        print(text, end="", file=destination, flush=True)
    return "".join(chunks)


async def run_seed_command(
    command: str,
    race: Race,
    interaction_id: int,
    project_directory: Path,
    seeds_directory: Path,
    extra_environment: dict[str, str] | None = None,
) -> Path:
    """Run a configured command and return its one resulting seed file."""
    seeds_directory.mkdir(parents=True, exist_ok=True)
    before = {
        path.resolve(): file_signature(path)
        for path in seeds_directory.rglob("*")
        if path.is_file()
    }
    environment = os.environ.copy()
    environment.update(
        {
            "RACE_GAME": race.game,
            "RACE_CATEGORY": race.category,
            "RACE_GUILD_ID": str(race.guild_id),
            "RACE_CHANNEL_ID": str(race.channel_id),
            "RACE_INTERACTION_ID": str(interaction_id),
            "RACE_SEEDS_DIRECTORY": str(seeds_directory.resolve()),
            "RACE_START_OPTIONS": json.dumps(race.start_options),
        }
    )
    if extra_environment:
        environment.update(extra_environment)
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=project_directory,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout, stderr = await asyncio.gather(
        capture_and_echo(process.stdout, sys.stdout),
        capture_and_echo(process.stderr, sys.stderr),
    )
    await process.wait()
    if process.returncode != 0:
        output = (stderr or stdout).strip()
        raise RuntimeError(f"Seed command exited with code {process.returncode}: {output[-500:]}")

    changed_files = []
    for path in seeds_directory.rglob("*"):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        resolved_path = path.resolve()
        if before.get(resolved_path) != file_signature(path):
            changed_files.append(resolved_path)
    if len(changed_files) != 1:
        raise RuntimeError(
            "The seed command must create or update exactly one file in the seeds directory. "
            f"Found {len(changed_files)}."
        )
    return changed_files[0]


async def ensure_seedbank(
    command: str | None,
    project_directory: Path,
    seedbank_directory: Path,
    game: str,
    minimum_seeds: int = 3,
) -> None:
    """Serialize checks and generation so refill jobs cannot overpopulate the bank."""
    async with _seedbank_generation_lock:
        await _populate_seedbank(
            command,
            project_directory,
            seedbank_directory,
            game,
            minimum_seeds,
        )


async def _populate_seedbank(
    command: str | None,
    project_directory: Path,
    seedbank_directory: Path,
    game: str,
    minimum_seeds: int,
) -> None:
    """Generate tournament seeds until the seed bank contains the requested minimum."""
    seedbank_directory.mkdir(parents=True, exist_ok=True)
    seed_count = sum(
        1 for path in seedbank_directory.rglob("*") if path.is_file() and path.name != ".gitkeep"
    )
    if seed_count >= minimum_seeds:
        logger.info("Seed bank already contains %s seed(s).", seed_count)
        return
    if not command:
        raise RuntimeError("SEED_GENERATOR_COMMAND is required to populate the seed bank.")

    missing_seeds = minimum_seeds - seed_count
    logger.info("Generating %s seed(s) to populate the seed bank.", missing_seeds)
    for offset in range(missing_seeds):
        interaction_id = time.time_ns() + offset
        race = Race(
            guild_id=0,
            channel_id=0,
            voice_channel_id=0,
            interaction_id=interaction_id,
            host_id=0,
            game=game,
            category=SEEDBANK_PRESET,
        )
        race.start_options = {
            "Randomizer preset": SEEDBANK_PRESET,
            "Music Rando": "true",
            "Tournament Mode": "true",
        }
        seed_path = await run_seed_command(
            command,
            race,
            interaction_id,
            project_directory,
            seedbank_directory,
            extra_environment={"RACE_SEEDBANK_GENERATION": "true"},
        )
        logger.info("Added seed-bank file: %s", seed_path.name)
