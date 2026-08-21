"""Optional randomizer seed-generation command support."""

import asyncio
import json
import os
from pathlib import Path

from speedrun_race_bot.models import Race


def file_signature(path: Path) -> tuple[int, int]:
    """Return values that identify a file version without reading its contents."""
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


async def run_seed_command(
    command: str, race: Race, project_directory: Path, seeds_directory: Path
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
            "RACE_SEEDS_DIRECTORY": str(seeds_directory.resolve()),
            "RACE_START_OPTIONS": json.dumps(race.start_options),
        }
    )
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=project_directory,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        output = (stderr or stdout).decode(errors="replace").strip()
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
