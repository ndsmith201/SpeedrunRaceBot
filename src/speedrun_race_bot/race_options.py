"""Loading and validation for configurable `/race create` options."""

from dataclasses import dataclass
from pathlib import Path
import re

import yaml


@dataclass(frozen=True)
class StartOption:
    """One Discord command parameter and its selectable values."""

    name: str
    parameter_name: str
    values: tuple[str, ...]


def _parameter_name(name: str) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", name.casefold()).strip("_")
    if not value or len(value) > 32:
        raise RuntimeError(
            "Race option names must produce a 1-32 character parameter name using letters, "
            "numbers, and underscores."
        )
    return value


def load_start_options(path: Path) -> list[StartOption]:
    """Load the configured command parameter list from the project YAML file."""
    if not path.is_file():
        raise RuntimeError(f"Race options file does not exist: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise RuntimeError(f"Could not parse race options YAML: {path}") from error
    if not isinstance(data, dict):
        raise RuntimeError("Race options YAML must contain a top-level mapping.")
    raw_options = data.get("race_start_options", [])

    if not isinstance(raw_options, list) or len(raw_options) > 22:
        raise RuntimeError("race_start_options may define at most 22 entries.")

    options = []
    parameter_names = set()
    for raw_option in raw_options:
        if not isinstance(raw_option, dict):
            raise RuntimeError("Every race_start_options entry must define name and value.")
        name = raw_option.get("name")
        values = raw_option.get("value")
        if not isinstance(name, str) or not name or not isinstance(values, list) or not values:
            raise RuntimeError(
                "Every race_start_options entry needs a non-empty string name and value list."
            )
        parameter_name = _parameter_name(name)
        if parameter_name in parameter_names:
            raise RuntimeError("Race option names must produce unique command parameter names.")
        parameter_names.add(parameter_name)
        if len(values) > 25:
            raise RuntimeError("Each race start option needs 1-25 values.")
        normalized_values = []
        for value in values:
            if value is None or isinstance(value, (list, dict)):
                raise RuntimeError("Race start option values must be scalar values.")
            normalized_value = str(value).lower() if isinstance(value, bool) else str(value)
            if not normalized_value:
                raise RuntimeError("Race start option values must not be empty.")
            normalized_values.append(normalized_value)
        if len(set(normalized_values)) != len(normalized_values) or any(
            len(value) > 100 for value in normalized_values
        ):
            raise RuntimeError("Race start option values must be unique and 100 characters or fewer.")
        options.append(StartOption(name, parameter_name, tuple(normalized_values)))
    return options
