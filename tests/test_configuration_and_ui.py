from pathlib import Path

from speedrun_race_bot.discord_ui.create_options import load_start_options
from speedrun_race_bot.discord_ui.tracker_template import load_tracker_template
from speedrun_race_bot.discord_ui.value_parsers import (
    is_country_flag_emoji,
    normalize_twitch_url,
)
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


def test_discord_value_parsers_and_timer_conversion() -> None:
    assert is_country_flag_emoji("🇺🇸")
    assert not is_country_flag_emoji("🏁")
    assert normalize_twitch_url("https://twitch.tv/Example_Name") == (
        "https://www.twitch.tv/Example_Name"
    )
    assert finish_time_to_milliseconds("01:02:03.004") == 3_723_004
