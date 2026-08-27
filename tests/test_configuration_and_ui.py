from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import yaml

from speedrun_race_bot.discord_ui.commands.race import RaceCommands
from speedrun_race_bot.discord_ui.create_options import load_start_options
from speedrun_race_bot.discord_ui.race_tracker import RaceTracker
from speedrun_race_bot.discord_ui.tracker_template import load_tracker_template
from speedrun_race_bot.discord_ui.value_parsers import (
    ASYNC_RACE_CLOSE_CHOICES,
    async_race_close_time,
    is_country_flag_emoji,
    normalize_twitch_url,
)
from speedrun_race_bot.domain import Race, RaceStatus
from speedrun_race_bot.race.state import RaceState
from speedrun_race_bot.race.time_format import finish_time_to_milliseconds


def test_repository_race_options_load() -> None:
    options = load_start_options(Path("config/race_options.yaml"))

    assert options
    assert options[0].parameter_name


def test_async_race_command_uses_configured_presets() -> None:
    commands = RaceCommands(SimpleNamespace(), load_start_options(Path("config/race_options.yaml")))

    async_command = commands.race.get_command("async")

    assert async_command is not None
    assert async_command.description.startswith("Start an async race")
    closes_at_parameter = next(
        parameter for parameter in async_command.parameters if parameter.name == "closes_at"
    )
    assert [(choice.name, choice.value) for choice in closes_at_parameter.choices] == list(
        ASYNC_RACE_CLOSE_CHOICES
    )


def test_tracker_template_contains_required_columns() -> None:
    template = load_tracker_template()

    assert template.section("column_racer_title") == "Racer"
    assert template.section("column_result_title") == "Result"
    assert template.section("column_elo_title") == "ELO"
    assert template.section("feedback_link") == (
        "[Report an issue or request a feature]"
        "(https://github.com/ndsmith201/SpeedrunRaceBot/issues/new?template=feedback.yml)"
    )


def test_feedback_issue_template_is_configured() -> None:
    issue_template = yaml.safe_load(
        Path(".github/ISSUE_TEMPLATE/feedback.yml").read_text(encoding="utf-8")
    )

    assert issue_template["name"] == "Bug report or feature request"
    assert [field["id"] for field in issue_template["body"]] == [
        "feedback_type",
        "summary",
        "details",
        "race_id",
        "proposed_solution",
        "additional_context",
        "checks",
    ]


def test_race_tracker_renders_feedback_link() -> None:
    bot = SimpleNamespace(get_guild=lambda guild_id: None)
    tracker = RaceTracker(bot, SimpleNamespace(), SimpleNamespace(), SimpleNamespace())
    race = Race(
        guild_id=1,
        channel_id=2,
        voice_channel_id=3,
        interaction_id=4,
        host_id=5,
        game="SotN",
        category="",
    )

    assert "Report an issue or request a feature" in tracker.markdown(race)
    assert "issues/new?template=feedback.yml" in tracker.markdown(race)


def test_discord_value_parsers_and_timer_conversion() -> None:
    assert is_country_flag_emoji("🇺🇸")
    assert not is_country_flag_emoji("🏁")
    assert normalize_twitch_url("https://twitch.tv/Example_Name") == (
        "https://www.twitch.tv/Example_Name"
    )
    assert finish_time_to_milliseconds("01:02:03.004") == 3_723_004
    start = datetime(2026, 8, 27, tzinfo=UTC)
    assert async_race_close_time(30 * 60, now=start) == start + timedelta(minutes=30)
    assert async_race_close_time(123, now=start) is None


def test_async_tracker_hides_results_until_the_race_closes() -> None:
    bot = SimpleNamespace(get_guild=lambda guild_id: None)
    users = SimpleNamespace(
        get_flag=lambda user_id: None,
        get_stream_url=lambda user_id: None,
        get_elo=lambda user_id: 1200,
    )
    tracker = RaceTracker(bot, users, SimpleNamespace(), SimpleNamespace())
    race = Race(
        guild_id=1,
        channel_id=2,
        voice_channel_id=None,
        interaction_id=4,
        host_id=5,
        game="SotN",
        category="",
        async_closes_at=datetime.now(UTC) + timedelta(hours=1),
    )
    races = RaceState()
    races.create(race)
    races.join(race, 10, "First")
    races.join(race, 20, "Second")
    races.start_async(race, started_at=datetime.now(UTC) - timedelta(minutes=5))
    races.finish(race, 10, "First")

    hidden_results = tracker.player_columns(race)[1][1]

    assert hidden_results.splitlines() == ["Hidden until close", "Hidden until close"]
    assert "00:05:" not in hidden_results

    races.complete_async(race)
    revealed_results = tracker.player_columns(race)[1][1]

    assert race.status is RaceStatus.COMPLETE
    assert "Hidden until close" not in revealed_results
    assert "Forfeit" in revealed_results
