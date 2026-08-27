import json
from typing import Self
from unittest.mock import patch
from urllib.error import HTTPError

from speedrun_race_bot.integrations.rando_api import RandoApiClient


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_ensure_user_returns_the_existing_api_player_name() -> None:
    client = RandoApiClient("https://example.test", "secret")

    with patch(
        "speedrun_race_bot.integrations.rando_api.urlopen",
        return_value=FakeResponse(b'{"user_id":"123","username":"Rando Nick"}'),
    ):
        api_name = client._ensure_user("discord-user", 123)

    assert api_name == "Rando Nick"


def test_ensure_user_registers_a_missing_user_with_the_current_schema() -> None:
    client = RandoApiClient("https://example.test", "secret")
    requests = []

    def request_side_effect(request, timeout: int) -> FakeResponse:
        requests.append(request)
        if len(requests) == 1:
            raise HTTPError(request.full_url, 404, "not found", {}, None)
        return FakeResponse(b'{"user_id":"123","username":"discord-user"}')

    with patch(
        "speedrun_race_bot.integrations.rando_api.urlopen",
        side_effect=request_side_effect,
    ):
        api_name = client._ensure_user("discord-user", 123)

    create_request = requests[1]
    assert api_name == "discord-user"
    assert create_request.full_url == "https://example.test/private/user"
    assert create_request.method == "POST"
    assert json.loads(create_request.data) == {
        "username": "discord-user",
        "user_id": "123",
    }
