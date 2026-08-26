"""Generate a SotN randomizer seed from the race command environment."""

import asyncio
import json
import logging
import os
import secrets
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import TextIO

from dotenv import load_dotenv

if __package__:
    from .seed_name_words import ADJECTIVES, NOUNS
else:
    from seed_name_words import ADJECTIVES, NOUNS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
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


def _required_path(variable: str, project_directory: Path) -> Path:
    value = os.getenv(variable, "").strip()
    if not value:
        raise RuntimeError(f"Set {variable} in the .env file.")
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_directory / path


def load_config() -> Config:
    """Load randomizer configuration from the project's .env file."""
    project_directory = Path(__file__).resolve().parent.parent
    load_dotenv(project_directory / ".env")
    interaction_id = os.getenv("RACE_INTERACTION_ID", "").strip()
    if not interaction_id:
        raise RuntimeError("RACE_INTERACTION_ID was not provided by the race bot.")
    try:
        parsed_interaction_id = int(interaction_id)
    except ValueError as error:
        raise RuntimeError("RACE_INTERACTION_ID must be an integer.") from error

    raw_start_options = os.getenv("RACE_START_OPTIONS", "").strip()
    if not raw_start_options:
        raise RuntimeError("RACE_START_OPTIONS was not provided by the race bot.")
    try:
        start_options = json.loads(raw_start_options)
    except json.JSONDecodeError as error:
        raise RuntimeError("RACE_START_OPTIONS must contain valid JSON.") from error
    if not isinstance(start_options, dict) or not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in start_options.items()
    ):
        raise RuntimeError("RACE_START_OPTIONS must contain a JSON object of string values.")

    return Config(
        interaction_id=parsed_interaction_id,
        start_options=start_options,
        seedbank_generation=os.getenv("RACE_SEEDBANK_GENERATION", "").casefold() == "true",
        rando_path=_required_path("RANDO_PATH", project_directory),
        patch_folder=_required_path("PATCH_FOLDER", project_directory),
        seeds_directory=_required_path("RACE_SEEDS_DIRECTORY", project_directory),
        replays_folder=_required_path("REPLAYS_FOLDER", project_directory),
        node_executable=os.getenv("NODE_EXECUTABLE", "node").strip() or "node",
    )


def _option_enabled(config: Config, name: str, *, default: bool = False) -> bool:
    value = config.start_options.get(name)
    if value is None:
        return default
    normalized_value = value.strip().casefold()
    if normalized_value not in {"true", "false"}:
        raise RuntimeError(f"Race option {name!r} must be either 'true' or 'false'.")
    return normalized_value == "true"


def generate_seed_name(category: str) -> str:
    """Return a random seed name in the form Category-AdjectiveNounNumber."""
    random_name = f"{secrets.choice(ADJECTIVES)}{secrets.choice(NOUNS)}{secrets.randbelow(99) + 1}"
    return f"{category}-{random_name}"


async def _run_process(*command: str, cwd: Path) -> tuple[str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_text, stderr_text = await asyncio.gather(
        _capture_and_echo(process.stdout, sys.stdout),
        _capture_and_echo(process.stderr, sys.stderr),
    )
    await process.wait()
    if process.returncode != 0:
        detail = (stderr_text or stdout_text).strip()
        raise RuntimeError(
            f"Command exited with code {process.returncode}: {detail[-1000:]}"
        )
    return stdout_text, stderr_text


async def _capture_and_echo(stream: asyncio.StreamReader, destination: TextIO) -> str:
    """Echo a subprocess stream live while retaining its text for error reporting."""
    chunks = []
    while chunk := await stream.readline():
        text = chunk.decode(errors="replace")
        chunks.append(text)
        print(text, end="", file=destination, flush=True)
    return "".join(chunks)


async def generate(
    seed_name: str,
    category: str,
    rando_music: bool,
    tournament: bool,
    *,
    config: Config,
) -> Path:
    patch_file_name = f"{seed_name}.ppf"
    patch_path = config.patch_folder / patch_file_name
    config.patch_folder.mkdir(parents=True, exist_ok=True)

    args = [
        "-o",
        str(patch_path),
        "-p",
        category,
        "-s",
        seed_name,
        "-l",
    ]
    if not rando_music and category != "boss-rush":
        args.extend(["--opt", "~m"])
    if tournament and category != "boss-rush":
        args.extend(["-t","--zr","--os"])

    command = [config.node_executable, str(config.randomizer_script), *args]
    logger.info("Generating seed with command: %s", command)
    try:
        await _run_process(*command, cwd=config.rando_path)

        if not config.seedbank_generation:
            replay_directory = config.replays_folder / str(config.interaction_id)
            replay_directory.mkdir(parents=True, exist_ok=False)
            (replay_directory / "raceInfo.json").write_text(
                json.dumps({"seedName": seed_name}, indent=2), encoding="utf-8"
            )

        config.seeds_directory.mkdir(parents=True, exist_ok=True)
        seed_output_path = config.seeds_directory / patch_file_name
        if patch_path.resolve() != seed_output_path.resolve():
            shutil.copy2(patch_path, seed_output_path)
        return seed_output_path
    except Exception:
        logger.exception("Seed generation failed for %s", seed_name)
        raise


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    sleep(1)
    print(f"Loaded randomizer configuration from {config.rando_path}")
    category = config.start_options.get("Randomizer preset", "").strip()
    if not category:
        raise RuntimeError("RACE_START_OPTIONS must include a Randomizer preset.")

    asyncio.run(
        generate(
            seed_name=generate_seed_name(category),
            category=category,
            rando_music=_option_enabled(config, "Music Rando"),
            tournament=_option_enabled(config, "Tournament Mode"),
            config=config,
        )
    )


if __name__ == "__main__":
    main()
