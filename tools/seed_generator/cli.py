"""Command-line entry point for generation from race environment variables."""

import asyncio
import logging
from time import sleep

from .config import load_config
from .naming import generate_seed_name
from .sotn import generate


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
            rando_music=config.option_enabled("Music Rando"),
            tournament=config.option_enabled("Tournament Mode"),
            config=config,
        )
    )
