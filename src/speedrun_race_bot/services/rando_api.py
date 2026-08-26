"""Client for the SotN Rando API user endpoints."""

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class RandoApiError(RuntimeError):
    """Raised when the Rando API cannot complete a request."""


class RandoApiClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def ensure_user(self, username: str, user_id: int) -> None:
        """Register a Discord user only when lookup by Discord ID returns 404."""
        await asyncio.to_thread(self._ensure_user, username, user_id)

    async def set_elo(self, user_id: int, preset: str, elo: int) -> None:
        """Set a user's absolute Elo for one randomizer preset."""
        await asyncio.to_thread(self._set_elo, user_id, preset, elo)

    async def create_current_race(self, preset: str) -> None:
        await asyncio.to_thread(
            self._send_current_race_request,
            "/private/currentrace/create",
            {"preset": preset},
        )

    async def add_current_racer(self, player_name: str) -> None:
        await asyncio.to_thread(
            self._send_current_race_request,
            "/private/currentrace/add",
            {"player_name": player_name},
        )

    async def remove_current_racer(self, player_name: str) -> None:
        await asyncio.to_thread(self._remove_current_racer, player_name)

    async def start_current_race(self) -> None:
        await asyncio.to_thread(self._start_current_race)

    async def finish_current_racer(
        self, player_name: str, finish_time: int | None, forfeited: bool
    ) -> None:
        await asyncio.to_thread(
            self._finish_current_racer, player_name, finish_time, forfeited
        )

    async def finish_current_race(self) -> None:
        await asyncio.to_thread(self._finish_current_race)

    def _finish_current_race(self) -> None:
        request = Request(
            f"{self.base_url}/private/currentrace/race/finish",
            data=b"",
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": self.api_key,
            },
        )
        try:
            with urlopen(request, timeout=10):
                return
        except HTTPError as error:
            raise RandoApiError(f"finish race returned HTTP {error.code}") from error
        except (URLError, TimeoutError) as error:
            reason = getattr(error, "reason", str(error))
            raise RandoApiError(f"finish race failed: {reason}") from error

    def _finish_current_racer(
        self, player_name: str, finish_time: int | None, forfeited: bool
    ) -> None:
        request = Request(
            f"{self.base_url}/private/currentrace/player/finish",
            data=json.dumps(
                {
                    "player_name": player_name,
                    "finish_time": finish_time,
                    "forfeited": forfeited,
                }
            ).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": self.api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=10):
                return
        except HTTPError as error:
            raise RandoApiError(f"finish racer returned HTTP {error.code}") from error
        except (URLError, TimeoutError) as error:
            reason = getattr(error, "reason", str(error))
            raise RandoApiError(f"finish racer failed: {reason}") from error

    def _start_current_race(self) -> None:
        request = Request(
            f"{self.base_url}/private/currentrace/start",
            data=b"",
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": self.api_key,
            },
        )
        try:
            with urlopen(request, timeout=10):
                return
        except HTTPError as error:
            raise RandoApiError(f"start race returned HTTP {error.code}") from error
        except (URLError, TimeoutError) as error:
            reason = getattr(error, "reason", str(error))
            raise RandoApiError(f"start race failed: {reason}") from error

    def _remove_current_racer(self, player_name: str) -> None:
        request = Request(
            f"{self.base_url}/private/currentrace/remove/{quote(player_name, safe='')}",
            method="DELETE",
            headers={
                "Accept": "application/json",
                "Authorization": self.api_key,
            },
        )
        try:
            with urlopen(request, timeout=10):
                return
        except HTTPError as error:
            raise RandoApiError(f"remove racer returned HTTP {error.code}") from error
        except (URLError, TimeoutError) as error:
            reason = getattr(error, "reason", str(error))
            raise RandoApiError(f"remove racer failed: {reason}") from error

    def _send_current_race_request(self, path: str, payload: dict[str, str]) -> None:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": self.api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=10):
                return
        except HTTPError as error:
            raise RandoApiError(f"current-race update returned HTTP {error.code}") from error
        except (URLError, TimeoutError) as error:
            reason = getattr(error, "reason", str(error))
            raise RandoApiError(f"current-race update failed: {reason}") from error

    def _set_elo(self, user_id: int, preset: str, elo: int) -> None:
        body = json.dumps(
            {
                "user_id": str(user_id),
                "preset": preset,
                "elo": elo,
                "set_elo": True,
            }
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/private/elo",
            data=body,
            method="PUT",
            headers={
                "Accept": "application/json",
                "Authorization": self.api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=10):
                return
        except HTTPError as error:
            raise RandoApiError(f"Elo update returned HTTP {error.code}") from error
        except (URLError, TimeoutError) as error:
            reason = getattr(error, "reason", str(error))
            raise RandoApiError(f"Elo update failed: {reason}") from error

    def _ensure_user(self, username: str, user_id: int) -> None:
        lookup = Request(
            f"{self.base_url}/user_by_id/{user_id}",
            headers={"Accept": "application/json"},
        )
        try:
            with urlopen(lookup, timeout=10):
                return
        except HTTPError as error:
            if error.code != 404:
                raise RandoApiError(f"user lookup returned HTTP {error.code}") from error
        except (URLError, TimeoutError) as error:
            reason = getattr(error, "reason", str(error))
            print(reason)
            raise RandoApiError(f"user lookup failed: {reason}") from error

        body = json.dumps({"username": username, "user_id": str(user_id)}).encode("utf-8")
        # create = Request(
        #     f"{self.base_url}/private/user",
        #     data=body,
        #     method="POST",
        #     headers={
        #         "Accept": "application/json",
        #         "Authorization": self.api_key,
        #         "Content-Type": "application/json",
        #     },
        # )
        # try:
        #     with urlopen(create, timeout=10):
        #         return
        # except HTTPError as error:
        #     raise RandoApiError(f"user registration returned HTTP {error.code}") from error
        # except (URLError, TimeoutError) as error:
        #     reason = getattr(error, "reason", str(error))
        #     raise RandoApiError(f"user registration failed: {reason}") from error
