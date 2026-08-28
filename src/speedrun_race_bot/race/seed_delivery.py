"""Background seed generation, seed-bank claims, and Discord delivery."""

import asyncio
import logging
import secrets
from pathlib import Path

import discord
from discord.ext import commands

from speedrun_race_bot.discord_ui.race_tracker import RaceTracker
from speedrun_race_bot.domain import Race
from speedrun_race_bot.integrations.seed_generator import (
    SEEDBANK_PRESET,
    ensure_seedbank,
    run_seed_command,
)
from speedrun_race_bot.race.state import RaceState

logger = logging.getLogger(__name__)


class SeedDelivery:
    """Generate or claim race seeds and attach them to their Discord race."""

    def __init__(
        self,
        bot: commands.Bot,
        tracker: RaceTracker,
        races: RaceState,
        command: str | None,
        project_directory: Path,
    ) -> None:
        self.bot = bot
        self.tracker = tracker
        self.races = races
        self.command = command
        self.project_directory = project_directory
        self.seeds_directory = project_directory / "seeds"
        self.seedbank_directory = project_directory / "seedbank"
        self.tasks: set[asyncio.Task[None]] = set()
        self.claim_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.command)

    def schedule(self, race: Race, interaction_id: int) -> None:
        task = asyncio.create_task(self.generate_and_attach(race, interaction_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def generate_and_attach(self, race: Race, interaction_id: int) -> None:
        """Generate the seed without delaying creation of the race lobby."""
        try:
            if self._uses_seedbank(race):
                seed_path = await self._claim_seedbank_seed()
                self._schedule_seedbank_refill()
            else:
                seed_path = await run_seed_command(
                    self.command or "",
                    race,
                    interaction_id,
                    self.project_directory,
                    self.seeds_directory,
                )
            race.seed_filename = seed_path.name
            race.seed_generation_in_progress = False
            self.races.save(race)

            if race.closed:
                seed_path.unlink(missing_ok=True)
                self.races.save(race)
                return

            await self.bot.wait_until_ready()
            channel = self.bot.get_channel(race.channel_id)
            if isinstance(channel, discord.TextChannel) and race.status_message_id:
                seed_message = await channel.send(
                    file=discord.File(seed_path, filename=seed_path.name)
                )
                race.seed_url = seed_message.attachments[0].url
                self.races.save(race)
                await self.tracker.update(race)
            seed_path.unlink()
        except Exception:
            race.seed_generation_in_progress = False
            race.seed_generation_error = True
            self.races.save(race)
            logger.exception("Seed generation failed for %s — %s", race.game, race.category)
            await self.tracker.update(race)

    @staticmethod
    def _uses_seedbank(race: Race) -> bool:
        preset = next(
            (
                value
                for name, value in race.start_options.items()
                if name.casefold() == "randomizer preset"
            ),
            "",
        )
        return preset.casefold() == SEEDBANK_PRESET

    async def _claim_seedbank_seed(self) -> Path:
        async with self.claim_lock:
            candidates = self._seedbank_files()
            if not candidates:
                await ensure_seedbank(
                    self.command,
                    self.project_directory,
                    self.seedbank_directory,
                    self.bot.settings.race_game,
                    minimum_seeds=1,
                )
                candidates = self._seedbank_files()
            if not candidates:
                raise RuntimeError("The seed bank is empty.")

            source_path = secrets.choice(candidates)
            self.seeds_directory.mkdir(parents=True, exist_ok=True)
            claimed_path = self.seeds_directory / source_path.name
            await asyncio.to_thread(source_path.replace, claimed_path)
            logger.info("Claimed seed-bank file: %s", source_path.name)
            return claimed_path

    def _seedbank_files(self) -> list[Path]:
        return [
            path
            for path in self.seedbank_directory.rglob("*")
            if path.is_file() and path.name != ".gitkeep"
        ]

    def _schedule_seedbank_refill(self) -> None:
        task = asyncio.create_task(self._refill_seedbank(), name="refill-seedbank")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _refill_seedbank(self) -> None:
        try:
            await ensure_seedbank(
                self.command,
                self.project_directory,
                self.seedbank_directory,
                self.bot.settings.race_game,
            )
        except Exception:
            logger.exception("Could not replenish the seed bank")
