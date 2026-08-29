import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from speedrun_race_bot.discord_ui.commands.race import RaceCommands
from speedrun_race_bot.discord_ui.controls import AsyncRaceView, JoinRaceView, RunningRaceView
from speedrun_race_bot.discord_ui.create_options import StartOption
from speedrun_race_bot.domain import Player, Race


def run(coroutine) -> None:
    asyncio.run(coroutine)


def interaction(*, user_id: int = 10, channel_id: int = 20):
    return SimpleNamespace(
        channel_id=channel_id,
        user=SimpleNamespace(id=user_id),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


def race(*, host_id: int = 10) -> Race:
    return Race(
        guild_id=1,
        channel_id=20,
        voice_channel_id=30,
        interaction_id=40,
        host_id=host_id,
        game="SotN",
        category="",
    )


def test_create_command_forwards_configured_options() -> None:
    coordinator = SimpleNamespace(create_race=AsyncMock())
    commands = RaceCommands(
        coordinator,
        [
            StartOption("Randomizer preset", "randomizer_preset", ("safe", "custom")),
            StartOption("Glitches", "glitches", ("allowed", "banned")),
        ],
    )
    command = commands.race.get_command("create")
    assert command is not None
    preset = command.callback.__annotations__["randomizer_preset"]
    glitches = command.callback.__annotations__["glitches"]
    race_channel = SimpleNamespace(id=20)
    voice_channel = SimpleNamespace(id=30)
    request = interaction()

    run(
        command.callback(
            request,
            race_channel,
            voice_channel,
            "Weekly race",
            preset.safe,
            glitches.banned,
        )
    )

    coordinator.create_race.assert_awaited_once_with(
        request,
        race_channel,
        voice_channel,
        "Weekly race",
        {"Randomizer preset": "safe", "Glitches": "banned"},
    )


def test_async_command_forwards_preset_and_close_duration() -> None:
    coordinator = SimpleNamespace(create_async_race=AsyncMock())
    commands = RaceCommands(
        coordinator,
        [StartOption("Randomizer preset", "randomizer_preset", ("safe", "custom"))],
    )
    command = commands.race.get_command("async")
    assert command is not None
    request = interaction()

    run(command.callback(request, "safe", 86_400))

    coordinator.create_async_race.assert_awaited_once_with(request, "safe", 86_400)


def test_close_command_reports_when_channel_has_no_race() -> None:
    service = SimpleNamespace(get=Mock(return_value=None))
    commands = RaceCommands(SimpleNamespace(service=service), [])
    request = interaction()

    run(RaceCommands.close_race.callback(commands, request))

    assert service.get.call_args_list == [
        ((20,), {"is_async": False}),
        ((20,), {"is_async": True}),
    ]
    request.response.send_message.assert_awaited_once_with(
        "There is no active race in this channel.", ephemeral=True
    )


def test_close_command_rejects_a_non_host() -> None:
    current_race = race(host_id=99)
    coordinator = SimpleNamespace(
        service=SimpleNamespace(get=Mock(return_value=current_race)),
        close_race=AsyncMock(),
    )
    commands = RaceCommands(coordinator, [])
    request = interaction(user_id=10)

    run(RaceCommands.close_race.callback(commands, request))

    request.response.send_message.assert_awaited_once_with(
        "Only the race host or a server administrator can close the race.", ephemeral=True
    )
    coordinator.close_race.assert_not_awaited()


def test_close_command_allows_the_host() -> None:
    current_race = race()
    coordinator = SimpleNamespace(
        service=SimpleNamespace(get=Mock(return_value=current_race)),
        close_race=AsyncMock(return_value="Race closed."),
    )
    commands = RaceCommands(coordinator, [])
    request = interaction()

    run(RaceCommands.close_race.callback(commands, request))

    request.response.defer.assert_awaited_once_with(ephemeral=True)
    coordinator.close_race.assert_awaited_once_with(current_race)
    request.followup.send.assert_awaited_once_with("Race closed.", ephemeral=True)


def test_close_command_allows_an_administrator() -> None:
    class FakeMember:
        def __init__(self) -> None:
            self.id = 10
            self.guild_permissions = SimpleNamespace(administrator=True)

    current_race = race(host_id=99)
    coordinator = SimpleNamespace(
        service=SimpleNamespace(get=Mock(return_value=current_race)),
        close_race=AsyncMock(return_value="Race closed."),
    )
    commands = RaceCommands(coordinator, [])
    request = interaction()
    request.user = FakeMember()

    with patch("speedrun_race_bot.discord_ui.commands.race.discord.Member", FakeMember):
        run(RaceCommands.close_race.callback(commands, request))

    coordinator.close_race.assert_awaited_once_with(current_race)


def test_playerkick_removes_the_api_and_local_racer() -> None:
    current_race = race()
    current_race.entrants[55] = Player(55, "Runner", "api-runner")
    coordinator = SimpleNamespace(
        service=SimpleNamespace(get=Mock(return_value=current_race), leave=Mock()),
        rando_api=SimpleNamespace(remove_current_racer=AsyncMock()),
        race_message=SimpleNamespace(update=AsyncMock()),
    )
    commands = RaceCommands(coordinator, [])
    request = interaction()
    player = SimpleNamespace(id=55, name="runner", mention="<@55>")

    run(RaceCommands.player_kick.callback(commands, request, player))

    coordinator.rando_api.remove_current_racer.assert_awaited_once_with("api-runner")
    coordinator.service.leave.assert_called_once_with(current_race, 55)
    coordinator.race_message.update.assert_awaited_once_with(current_race)
    request.response.send_message.assert_awaited_once_with(
        "Removed <@55> from the race.", ephemeral=True
    )


def test_lobby_buttons_delegate_and_only_report_errors() -> None:
    async def exercise() -> None:
        coordinator = SimpleNamespace(
            join_race=AsyncMock(return_value="There is no active race in this channel."),
            ready_racer=AsyncMock(return_value="You are marked ready!"),
            start_race=AsyncMock(),
        )
        view = JoinRaceView(coordinator)

        join_request = interaction()
        await view.join_button.callback(join_request)
        join_request.response.defer.assert_awaited_once_with()
        coordinator.join_race.assert_awaited_once_with(join_request, is_async=False)
        join_request.followup.send.assert_awaited_once_with(
            "There is no active race in this channel.", ephemeral=True
        )

        ready_request = interaction()
        await view.ready_button.callback(ready_request)
        coordinator.ready_racer.assert_awaited_once_with(ready_request)
        ready_request.followup.send.assert_not_awaited()

        start_request = interaction()
        await view.start_button.callback(start_request)
        coordinator.start_race.assert_awaited_once_with(start_request, silent=True)

    run(exercise())


def test_running_buttons_report_coordinator_errors() -> None:
    async def exercise() -> None:
        coordinator = SimpleNamespace(
            record_finish=AsyncMock(return_value="Join the race before finishing."),
            record_forfeit=AsyncMock(return_value=None),
        )
        view = RunningRaceView(coordinator)

        finish_request = interaction()
        await view.finish_button.callback(finish_request)
        coordinator.record_finish.assert_awaited_once_with(finish_request, is_async=False)
        finish_request.followup.send.assert_awaited_once_with(
            "Join the race before finishing.", ephemeral=True
        )

        forfeit_request = interaction()
        await view.forfeit_button.callback(forfeit_request)
        coordinator.record_forfeit.assert_awaited_once_with(forfeit_request, is_async=False)
        forfeit_request.followup.send.assert_not_awaited()

    run(exercise())


def test_async_buttons_always_send_private_confirmation() -> None:
    async def exercise() -> None:
        coordinator = SimpleNamespace(
            join_race=AsyncMock(return_value="You joined the race!"),
            record_finish=AsyncMock(return_value=None),
            record_forfeit=AsyncMock(return_value="This async race is closed."),
        )
        view = AsyncRaceView(coordinator)

        join_request = interaction()
        await view.join_button.callback(join_request)
        join_request.response.defer.assert_awaited_once_with(ephemeral=True)
        coordinator.join_race.assert_awaited_once_with(join_request, is_async=True)
        join_request.followup.send.assert_awaited_once_with("You joined the race!", ephemeral=True)

        finish_request = interaction()
        await view.finish_button.callback(finish_request)
        finish_request.followup.send.assert_awaited_once_with(
            "Your finish time was recorded privately and will be revealed at close.",
            ephemeral=True,
        )

        forfeit_request = interaction()
        await view.forfeit_button.callback(forfeit_request)
        forfeit_request.followup.send.assert_awaited_once_with(
            "This async race is closed.", ephemeral=True
        )

    run(exercise())
