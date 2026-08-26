"""SotN randomizer invocation and generated artifact placement."""

import json
import logging
import shutil
from pathlib import Path

from .config import SeedGeneratorConfig
from .process import run_process

logger = logging.getLogger(__name__)


async def generate(
    seed_name: str,
    category: str,
    rando_music: bool,
    tournament: bool,
    *,
    config: SeedGeneratorConfig,
) -> Path:
    patch_file_name = f"{seed_name}.ppf"
    patch_path = config.patch_folder / patch_file_name
    config.patch_folder.mkdir(parents=True, exist_ok=True)

    args = ["-o", str(patch_path), "-p", category, "-s", seed_name, "-l"]
    if not rando_music and category != "boss-rush":
        args.extend(["--opt", "~m"])
    if tournament and category != "boss-rush":
        args.extend(["-t", "--zr", "--os"])

    command = [config.node_executable, str(config.randomizer_script), *args]
    logger.info("Generating seed with command: %s", command)
    try:
        await run_process(*command, cwd=config.rando_path)
        if not config.seedbank_generation:
            _write_replay_metadata(config, seed_name)
        return _copy_seed_to_output(config, patch_path, patch_file_name)
    except Exception:
        logger.exception("Seed generation failed for %s", seed_name)
        raise


def _write_replay_metadata(config: SeedGeneratorConfig, seed_name: str) -> None:
    replay_directory = config.replays_folder / str(config.interaction_id)
    replay_directory.mkdir(parents=True, exist_ok=False)
    (replay_directory / "raceInfo.json").write_text(
        json.dumps({"seedName": seed_name}, indent=2), encoding="utf-8"
    )


def _copy_seed_to_output(config: SeedGeneratorConfig, patch_path: Path, filename: str) -> Path:
    config.seeds_directory.mkdir(parents=True, exist_ok=True)
    output_path = config.seeds_directory / filename
    if patch_path.resolve() != output_path.resolve():
        shutil.copy2(patch_path, output_path)
    return output_path
