"""Read configured race-start options from the process environment."""

import json
import os
from typing import Any


def get_race_start_options() -> dict[str, Any]:
    """Parse the RACE_START_OPTIONS JSON environment variable into a dictionary."""
    raw_options = os.getenv("RACE_START_OPTIONS")
    if raw_options is None:
        raise RuntimeError("RACE_START_OPTIONS is not set.")

    try:
        options = json.loads(raw_options)
    except json.JSONDecodeError as error:
        raise ValueError("RACE_START_OPTIONS must contain valid JSON.") from error

    if not isinstance(options, dict):
        raise ValueError("RACE_START_OPTIONS must contain a JSON object.")
    return options


if __name__ == "__main__":
    print(get_race_start_options())
