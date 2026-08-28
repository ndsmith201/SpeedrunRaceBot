"""Finish, forfeit, Elo calculation, and result synchronization workflows."""

import asyncio
import logging

import discord

from speedrun_race_bot.discord_ui.race_tracker import RaceTracker
from speedrun_race_bot.domain import Race, RaceStatus
from speedrun_race_bot.integrations.rando_api import RandoApiClient, RandoApiError
from speedrun_race_bot.persistence import UserRepository
from speedrun_race_bot.race.elo import EloService
from speedrun_race_bot.race.state import RaceState
from speedrun_race_bot.race.time_format import finish_time_to_milliseconds

logger = logging.getLogger(__name__)


class RaceResults:
    def __init__(
        self,
        races: RaceState,
        users: UserRepository,
        elo: EloService,
        api: RandoApiClient,
        tracker: RaceTracker,
    ) -> None:
        self.races = races
        self.users = users
        self.elo = elo
        self.api = api
        self.tracker = tracker

    async def record_finish(
        self, interaction: discord.Interaction, *, is_async: bool | None = None
    ) -> str | None:
        race = self.races.get(interaction.channel_id or 0, is_async=is_async)
        if not race:
            return "There is no active race in this channel."
        entrant = race.entrants.get(interaction.user.id)
        retrying_api = bool(
            entrant and entrant.finish_position is not None and not entrant.api_result_synced
        )
        retrying_completion = bool(
            entrant
            and entrant.finish_position is not None
            and entrant.api_result_synced
            and race.status is RaceStatus.COMPLETE
            and not race.api_race_finished
        )
        if not retrying_api and not retrying_completion:
            try:
                self.races.finish(race, interaction.user.id, interaction.user.display_name)
            except ValueError as error:
                return str(error)
            entrant = race.entrants[interaction.user.id]
        if race.is_async:
            entrant.mark_api_result_synced()
            self.races.save(race)
        elif not entrant.api_result_synced:
            if not entrant.api_name:
                entrant.api_name = interaction.user.name
                self.races.save(race)
            try:
                await self.api.finish_current_racer(
                    entrant.api_name,
                    finish_time_to_milliseconds(entrant.finish_time or "00:00:00.000"),
                    False,
                )
            except RandoApiError as error:
                logger.warning("Could not synchronize racer finish: %s", error)
                return f"Your finish was recorded locally, but API synchronization failed: {error}"
            entrant.mark_api_result_synced()
            self.races.save(race)
        elo_error = await self.update_elo_if_complete(race)
        await self.tracker.update(race)
        return elo_error

    async def record_forfeit(
        self, interaction: discord.Interaction, *, is_async: bool | None = None
    ) -> str | None:
        race = self.races.get(interaction.channel_id or 0, is_async=is_async)
        if not race:
            return "There is no active race in this channel."
        entrant = race.entrants.get(interaction.user.id)
        retrying_api = bool(entrant and entrant.forfeited and not entrant.api_result_synced)
        retrying_completion = bool(
            entrant
            and entrant.forfeited
            and entrant.api_result_synced
            and race.status is RaceStatus.COMPLETE
            and not race.api_race_finished
        )
        if not retrying_api and not retrying_completion:
            try:
                self.races.forfeit(race, interaction.user.id)
            except ValueError as error:
                return str(error)
            entrant = race.entrants[interaction.user.id]
        if race.is_async:
            entrant.mark_api_result_synced()
            self.races.save(race)
        elif not entrant.api_result_synced:
            if not entrant.api_name:
                entrant.api_name = interaction.user.name
                self.races.save(race)
            try:
                await self.api.finish_current_racer(entrant.api_name, None, True)
            except RandoApiError as error:
                logger.warning("Could not synchronize racer forfeit: %s", error)
                return f"Your forfeit was recorded locally, but API synchronization failed: {error}"
            entrant.mark_api_result_synced()
            self.races.save(race)
        elo_error = await self.update_elo_if_complete(race)
        await self.tracker.update(race)
        return elo_error

    async def finalize_async_race(self, race: Race) -> str | None:
        """Close local-only async submissions and publish final results."""
        self.races.complete_async(race)
        for entrant in race.entrants.values():
            if not entrant.api_result_synced:
                entrant.mark_api_result_synced()
        self.races.save(race)

        elo_error = await self.update_elo_if_complete(race)
        await self.tracker.update(race)
        return elo_error

    async def update_elo_if_complete(self, race: Race) -> str | None:
        """Persist Elo once, then synchronize every new rating to the API."""
        if race.status is not RaceStatus.COMPLETE:
            return None
        if not all(entrant.api_result_synced for entrant in race.entrants.values()):
            return "Elo is waiting for every racer result to synchronize with the API."
        if not race.elo_processed:
            forfeited_placement = len(race.entrants)
            placements = {
                user_id: entrant.finish_position or forfeited_placement
                for user_id, entrant in race.entrants.items()
            }
            race.elo_changes = self.elo.apply(placements)
            race.elo_processed = True
        self.races.save_result(race)
        if race.is_async:
            race.elo_api_synced = True
            race.api_race_finished = True
            self.races.save(race)
            return None
        if not race.elo_api_synced:
            preset = self._preset(race)
            if not preset:
                return "Elo was saved locally, but the API update needs a randomizer preset."
            try:
                await asyncio.gather(
                    *(
                        self.api.set_elo(user_id, preset, self.users.get_elo(user_id))
                        for user_id in race.entrants
                    )
                )
            except RandoApiError as error:
                logger.warning("Could not synchronize race Elo: %s", error)
                return f"Elo was saved locally, but API synchronization failed: {error}"
            race.elo_api_synced = True
            self.races.save(race)
        if not race.api_race_finished:
            try:
                await self.api.finish_current_race()
            except RandoApiError as error:
                logger.warning("Could not finish current API race: %s", error)
                return f"Results and Elo were saved, but API race finalization failed: {error}"
            race.api_race_finished = True
            self.races.save(race)
        return None

    async def adjust_elo(self, race_id: int, ordered_user_ids: list[int]) -> str:
        """Replace a completed race's Elo result with an administrator-supplied order."""
        race = self.races.get_by_interaction_id(race_id)
        if not race:
            return f"I couldn't find race `{race_id}` in this bot session."
        if race.status is not RaceStatus.COMPLETE or not race.elo_processed:
            return "That race has not completed its Elo adjustment yet."
        validation_error = self._validate_adjustment_order(race, ordered_user_ids)
        if validation_error:
            return validation_error

        try:
            new_changes = self.elo.adjust(race.elo_changes, ordered_user_ids)
        except (RuntimeError, ValueError) as error:
            return f"Elo adjustment failed: {error}"

        race.elo_changes = new_changes
        race.elo_api_synced = False
        self.races.save_result(race)
        preset = self._preset(race)
        if preset:
            try:
                await asyncio.gather(
                    *(
                        self.api.set_elo(user_id, preset, self.users.get_elo(user_id))
                        for user_id in ordered_user_ids
                    )
                )
            except RandoApiError as error:
                logger.warning("Could not synchronize adjusted race Elo: %s", error)
                await self.tracker.update(race)
                return f"Elo was adjusted locally, but API synchronization failed: {error}"
            race.elo_api_synced = True
            self.races.save(race)

        await self.tracker.update(race)
        order = " → ".join(f"<@{user_id}>" for user_id in ordered_user_ids)
        return f"Adjusted Elo for race `{race_id}` using this finish order: {order}."

    @staticmethod
    def _preset(race: Race) -> str | None:
        return next(
            (
                value
                for name, value in race.start_options.items()
                if name.casefold() == "randomizer preset"
            ),
            None,
        )

    @staticmethod
    def _validate_adjustment_order(race: Race, ordered_user_ids: list[int]) -> str | None:
        if not ordered_user_ids:
            return "Supply every racer in finish order."
        if len(set(ordered_user_ids)) != len(ordered_user_ids):
            return "Each racer may only appear once."
        entrant_ids = set(race.entrants)
        supplied_ids = set(ordered_user_ids)
        if entrant_ids == supplied_ids:
            return None
        missing = entrant_ids - supplied_ids
        extra = supplied_ids - entrant_ids
        details = []
        if missing:
            details.append("missing " + ", ".join(f"<@{user_id}>" for user_id in sorted(missing)))
        if extra:
            details.append("not in race " + ", ".join(f"<@{user_id}>" for user_id in sorted(extra)))
        return "The order must contain every racer exactly once (" + "; ".join(details) + ")."
