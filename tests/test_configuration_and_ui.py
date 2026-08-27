from pathlib import Path
from types import SimpleNamespace

import yaml

from speedrun_race_bot.discord_ui.create_options import load_start_options
from speedrun_race_bot.discord_ui.race_tracker import RaceTracker
from speedrun_race_bot.discord_ui.tracker_template import load_tracker_template
from speedrun_race_bot.discord_ui.value_parsers import (
    is_country_flag_emoji,
    normalize_twitch_url,
)
from speedrun_race_bot.domain import Race
from speedrun_race_bot.race.time_format import finish_time_to_milliseconds


def test_repository_race_options_load() -> None:
    options = load_start_options(Path("config/race_options.yaml"))

    assert options
    assert options[0].parameter_name


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
